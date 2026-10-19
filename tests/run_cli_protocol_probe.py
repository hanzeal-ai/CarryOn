"""Real Codex TUI + CarryOn adapter against an isolated socket and local model.

Exercises the production CLI transport and common protocol adapter. No desktop IPC,
real credentials, or real model API is required. Evidence stays in --output.
"""
import argparse
import base64
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from carryon.codex_cli.client import CliClient
from carryon.routes.websocket import WebSocket


def wait(check, description, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.03)
    raise AssertionError('Timed out: ' + description)


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


class Fixture:
    def __init__(self, work, output):
        self.work, self.output = work, output
        self.gates = {}
        self.lock = threading.Lock()
        self.calls = []

    def gate(self, name):
        with self.lock:
            return self.gates.setdefault(name, threading.Event())

    def handler(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                inputs = body.get('input', [])
                last = max((i for i, v in enumerate(inputs) if v.get('role') == 'user'), default=-1)
                prompt = ' '.join(c.get('text', '') for c in inputs[last].get('content', [])) if last >= 0 else 'SEED'
                tag = next((t for t in ['CLI_STREAM', 'CARRYON_STREAM', 'APPROVAL_CARRYON',
                    'APPROVAL_CLI', 'LATE_APPROVAL', 'DISCONNECT_CARRYON', 'DISCONNECT_CLI',
                    'DISCONNECT_ALL', 'RECONNECT'] if t in prompt), 'SEED')
                tool_done = any(v.get('type') == 'function_call_output' for v in inputs[last + 1:])
                with fixture.lock:
                    fixture.calls.append({'tag': tag, 'toolDone': tool_done,
                        'toolNames': [v.get('name') for v in body.get('tools', [])]})
                uid = uuid.uuid4().hex
                response = {'id': 'resp_' + uid, 'object': 'response', 'status': 'in_progress', 'output': []}
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()

                def emit(event):
                    self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                    self.wfile.flush()

                try:
                    emit({'type': 'response.created', 'response': response})
                    if 'APPROVAL' in tag and not tool_done and any(t.get('name') == 'exec_command' for t in body.get('tools', [])):
                        marker = fixture.work / (tag.lower() + '.txt')
                        code = 'from pathlib import Path; Path(' + repr(str(marker)) + ').open("a").write("approved\\n")'
                        args = {'cmd': shlex.quote(sys.executable) + ' -c ' + shlex.quote(code),
                            'workdir': str(fixture.work), 'login': False, 'yield_time_ms': 1000,
                            'sandbox_permissions': 'require_escalated',
                            'justification': 'Allow the isolated protocol fixture to write its marker?'}
                        item = {'id': 'fc_' + uid, 'type': 'function_call', 'call_id': 'call_' + uid,
                            'name': 'exec_command', 'arguments': json.dumps(args), 'status': 'completed'}
                        emit({'type': 'response.output_item.added', 'output_index': 0,
                            'item': {**item, 'arguments': '', 'status': 'in_progress'}})
                        emit({'type': 'response.function_call_arguments.delta', 'output_index': 0,
                            'item_id': item['id'], 'delta': item['arguments']})
                    else:
                        text = tag + '_ALPHA_\nOMEGA'
                        item = {'id': 'msg_' + uid, 'type': 'message', 'role': 'assistant',
                            'status': 'completed', 'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}
                        emit({'type': 'response.output_item.added', 'output_index': 0,
                            'item': {**item, 'content': [], 'status': 'in_progress'}})
                        emit({'type': 'response.output_text.delta', 'item_id': item['id'],
                            'output_index': 0, 'content_index': 0, 'delta': tag + '_ALPHA_\n'})
                        if body.get('tools') and (tag.startswith('DISCONNECT') or tag.endswith('_STREAM')):
                            if not fixture.gate(tag).wait(30):
                                raise TimeoutError('fixture gate ' + tag)
                        emit({'type': 'response.output_text.delta', 'item_id': item['id'],
                            'output_index': 0, 'content_index': 0, 'delta': 'OMEGA'})
                    emit({'type': 'response.output_item.done', 'output_index': 0, 'item': item})
                    emit({'type': 'response.completed', 'response': {**response, 'status': 'completed',
                        'output': [item], 'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13}}})
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    self.close_connection = True

        return Handler


class SocketAdapter(CliClient):
    """Production adapter with wire capture only."""
    def __init__(self, home, endpoint, output, name):
        super().__init__(home, socket_path=endpoint)
        self.output, self.name = output, name
        self.wire = []
        self.reader_errors = []
        self.log_lock = threading.Lock()

    def log(self, direction, message):
        row = {'time': time.monotonic(), 'direction': direction, 'message': message}
        with self.log_lock:
            self.wire.append(row)
            with (self.output / (self.name + '-wire.jsonl')).open('a') as stream:
                stream.write(json.dumps(row) + '\n')

    def _write(self, message):
        self.log('send', message)
        super()._write(message)

    def receive(self, message):
        self.log('receive', message)
        super().receive(message)

    def received(self, method, after=0):
        return [r['message'] for r in self.wire[after:] if r['direction'] == 'receive'
            and r['message'].get('method') == method]


class Terminal:
    def __init__(self, executable, env, work, endpoint, tid, output, prompt=None):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 50, 180, 0, 0))
        command = [executable] + (['resume'] if tid else [])
        if endpoint: command += ['--remote', 'unix://' + str(endpoint)]
        if tid: command += [tid]
        command += ['--no-alt-screen']
        if prompt:
            command.append(prompt)
        self.process = subprocess.Popen(command, env=env, cwd=work, stdin=slave,
            stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        self.chunks, self.output = [], output
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        with self.output.open('wb') as log:
            while True:
                try:
                    if not select.select([self.master], [], [], .1)[0]:
                        if self.process.poll() is not None:
                            break
                        continue
                    data = os.read(self.master, 65536)
                    if not data:
                        break
                    self.chunks.append(data)
                    log.write(data); log.flush()
                    if b'\x1b[6n' in data:
                        os.write(self.master, b'\x1b[1;1R')
                    if b'\x1b[c' in data:
                        os.write(self.master, b'\x1b[?1;2c')
                except OSError:
                    break

    def text(self):
        return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', b''.join(self.chunks).decode(errors='replace'))

    def send(self, text):
        os.write(self.master, text.encode())
        time.sleep(.15)
        os.write(self.master, b'\r')

    def close(self):
        stop(self.process)
        self.reader.join(timeout=2)
        os.close(self.master)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', default=shutil.which('codex'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'checks': [], 'limitations': [], 'codexVersion': subprocess.check_output([args.codex, '--version'], text=True).strip()}
    daemon = terminal = adapter = observer = None
    with tempfile.TemporaryDirectory(prefix='carryon-cli-probe-') as temporary:
        root = Path(temporary).resolve()
        home, work, endpoint = root / 'home', root / 'work', root / 'server.sock'
        home.mkdir(); work.mkdir()
        fixture = Fixture(work, output)
        model = ThreadingHTTPServer(('127.0.0.1', 0), fixture.handler())
        model.daemon_threads = True
        threading.Thread(target=model.serve_forever, daemon=True).start()
        env = {k: v for k, v in os.environ.items() if k not in
            ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_THREAD_ID', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE')}
        env.update(CODEX_HOME=str(home), TERM='xterm-256color', NO_COLOR='1')
        (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
            'approval_policy="on-request"\nsandbox_mode="workspace-write"\n'
            f'[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:{model.server_port}/v1"\n'
            f'wire_api="responses"\nrequires_openai_auth=false\n[projects."{work}"]\ntrust_level="trusted"\n')

        def check(name, evidence):
            report['checks'].append({'name': name, 'passed': True, 'evidence': evidence})
            print('PASS', name, flush=True)

        def open_adapter(name):
            result = SocketAdapter(home, endpoint, output, name)
            result.connect()
            return result

        def completed(turn_id, peer=None):
            peer = peer or adapter
            events = peer.received('turn/completed')
            return next((e for e in events if e['params']['turn']['id'] == turn_id), None)

        def start(tag):
            return adapter.rpc('turn/start', {'threadId': tid,
                'input': [{'type': 'text', 'text': tag, 'text_elements': []}]})['turn']['id']

        def delta(tag, peer=None, after=0):
            return next((e for e in (peer or adapter).received('item/agentMessage/delta', after)
                if tag + '_ALPHA_' in e['params']['delta']), None)

        try:
            with (output / 'server-stdout.log').open('w') as stdout, (output / 'server-stderr.log').open('w') as stderr:
                daemon = subprocess.Popen([args.codex, 'app-server', '--listen', 'unix://' + str(endpoint)],
                    cwd=work, env=env, stdout=stdout, stderr=stderr)
            wait(endpoint.exists, 'server socket')
            adapter = open_adapter('carryon-probe')
            tid = adapter.create_thread({'cwd': str(work), 'historyMode': 'paginated',
                'approvalPolicy': 'on-request'}, lambda write: write())['id']
            report.update(threadId=tid, serverPid=daemon.pid)
            seed = start('SEED')
            assert wait(lambda: completed(seed), 'seed completion')['params']['turn']['status'] == 'completed'
            terminal = Terminal(args.codex, env, work, endpoint, tid, output / 'cli-terminal.log', 'CLI_STREAM')
            wait(lambda: delta('CLI_STREAM'), 'CLI turn reaches CarryOn')
            running = adapter.current(tid)['turns'][-1]
            assert running['status'] == 'inProgress'
            assert not completed(running['id'])
            assert any('CLI_STREAM_ALPHA_' in i.get('text', '') for i in running['items'])
            assert terminal.process.poll() is None and daemon.poll() is None
            check('CLI → CarryOn live delta before completion', {'turnId': running['id'], 'status': running['status']})
            fixture.gate('CLI_STREAM').set()
            wait(lambda: completed(running['id']), 'CLI turn completion')
            turn_id = start('CARRYON_STREAM')
            wait(lambda: delta('CARRYON_STREAM'), 'CarryOn streaming')
            wait(lambda: 'CARRYON_STREAM_ALPHA_' in terminal.text(), 'CarryOn delta appears in CLI')
            assert not completed(turn_id)
            check('CarryOn → CLI live delta before completion', {'turnId': turn_id, 'terminalEvidence': 'CARRYON_STREAM_ALPHA_'})
            fixture.gate('CARRYON_STREAM').set()
            wait(lambda: completed(turn_id), 'CarryOn turn completion')
            observer = open_adapter('observer')
            observer.snapshot(tid)
            check('second protocol client resumes same loaded thread', {'threadId': tid})

            # Real command approval generated by the native engine; only fixture files are written.
            for tag, answer_in_cli in [('APPROVAL_CARRYON', False), ('APPROVAL_CLI', True)]:
                offset = len(adapter.wire)
                terminal_offset = len(terminal.text())
                if answer_in_cli:
                    turn_id = start(tag)
                else:
                    terminal.send(tag)
                    turn_id = wait(lambda: next(iter(adapter.received('turn/started', offset)), None), 'CLI starts approval turn')['params']['turn']['id']
                request = wait(lambda: next(iter(adapter.received('item/commandExecution/requestApproval', offset)), None), tag + ' request')
                wait(lambda: next((e for e in observer.received('item/commandExecution/requestApproval') if e['id'] == request['id']), None), 'approval broadcast')
                marker = work / (tag.lower() + '.txt')
                assert not marker.exists()
                wait(lambda: 'Press enter to confirm' in terminal.text()[terminal_offset:]
                    and tag.lower() + '.txt' in terminal.text()[terminal_offset:], 'CLI displays approval choices')
                if answer_in_cli:
                    terminal.send('')
                else:
                    adapter.respond(tid, {'requestId': request['id'], 'decision': 'accept'}, lambda write: write(), 10000)
                wait(marker.exists, tag + ' command executes')
                assert wait(lambda: completed(turn_id), tag + ' completion')['params']['turn']['status'] == 'completed'
                wait(lambda: any(e['params'].get('requestId') == request['id'] for e in observer.received('serverRequest/resolved')), 'other client resolves approval')
                assert not adapter.current(tid)['requests']
                # A stale reply from another subscriber must not execute a second command.
                observer._write({'id': request['id'], 'result': {'decision': 'accept'}})
                observer.rpc('thread/read', {'threadId': tid, 'includeTurns': False})
                assert marker.read_text() == 'approved\n'
                check(tag + ' single approval resolves all protocol clients', {'requestId': request['id'], 'turnId': turn_id,
                    'origin': 'carryon' if answer_in_cli else 'cli', 'marker': marker.read_text(), 'staleReplyDidNotExecuteAgain': True})

            turn_id = start('DISCONNECT_CARRYON')
            wait(lambda: delta('DISCONNECT_CARRYON'), 'CarryOn disconnect stream')
            adapter.close()
            assert daemon.poll() is None and terminal.process.poll() is None
            fixture.gate('DISCONNECT_CARRYON').set()
            assert wait(lambda: completed(turn_id, observer), 'completion after CarryOn disconnect')['params']['turn']['status'] == 'completed'
            wait(lambda: 'DISCONNECT_CARRYON_ALPHA_' in terminal.text(), 'CLI receives disconnected CarryOn turn')
            adapter = open_adapter('carryon-reconnected')
            _, state = adapter.snapshot(tid)
            assert any(t['id'] == turn_id and t['status'] == 'completed' for t in state['turns'])
            check('CarryOn disconnect preserves execution and reconnect recovers history', {'turnId': turn_id, 'sameServerPid': daemon.pid})

            offset = len(adapter.wire)
            terminal.send('DISCONNECT_CLI')
            turn_id = wait(lambda: next(iter(adapter.received('turn/started', offset)), None), 'CLI starts disconnect turn')['params']['turn']['id']
            wait(lambda: delta('DISCONNECT_CLI'), 'CLI disconnect stream')
            terminal.close(); terminal = None
            assert daemon.poll() is None
            fixture.gate('DISCONNECT_CLI').set()
            assert wait(lambda: completed(turn_id), 'completion after CLI disconnect')['params']['turn']['status'] == 'completed'
            check('CLI disconnect preserves execution', {'turnId': turn_id, 'sameServerPid': daemon.pid})

            turn_id = start('DISCONNECT_ALL')
            wait(lambda: delta('DISCONNECT_ALL'), 'all clients disconnect stream')
            adapter.close(); observer.close(); observer = None
            assert daemon.poll() is None
            fixture.gate('DISCONNECT_ALL').set()
            wait(lambda: any(c['tag'] == 'DISCONNECT_ALL' for c in fixture.calls), 'fixture call recorded')
            time.sleep(.5)
            adapter = open_adapter('carryon-after-all-disconnect')
            # Read persisted history before any resume: reconnect cannot restart this task.
            wait(lambda: any(t['id'] == turn_id and t['status'] == 'completed'
                for t in adapter.read_turns(tid)), 'persisted completion after all clients disconnect')
            check('all clients disconnect preserves task in independent server', {'turnId': turn_id,
                'sameServerPid': daemon.pid, 'verifiedWithoutResume': True})
            adapter.snapshot(tid)
            offset = len(adapter.wire)
            turn_id = start('LATE_APPROVAL')
            request = wait(lambda: next(iter(adapter.received('item/commandExecution/requestApproval', offset)), None), 'late approval request')
            adapter.close()
            assert daemon.poll() is None
            observer = open_adapter('late-subscriber')
            observer.snapshot(tid)
            replay = wait(lambda: next((e for e in observer.received('item/commandExecution/requestApproval')
                if e['params']['turnId'] == turn_id), None), 'pending approval replay on late subscription')
            assert replay['id'] == request['id']
            wait(lambda: any(r['id'] == replay['id'] for r in observer.current(tid)['requests']), 'pending approval in CarryOn snapshot')
            observer.respond(tid, {'requestId': replay['id'], 'decision': 'accept'}, lambda write: write(), 10000)
            assert wait(lambda: completed(turn_id, observer), 'late subscriber completes approval')['params']['turn']['status'] == 'completed'
            assert (work / 'late_approval.txt').read_text() == 'approved\n'
            check('reconnect after all clients disconnect recovers pending approval',
                {'requestId': replay['id'], 'turnId': turn_id})
            assert not adapter.reader_errors, adapter.reader_errors
            report['passed'] = True
        except Exception as exc:
            report['passed'] = False
            report['error'] = repr(exc)
            print('FAILED', repr(exc), flush=True)
        finally:
            for gate in fixture.gates.values():
                gate.set()
            if terminal:
                terminal.close()
            for peer in (adapter, observer):
                if peer:
                    peer.close()
                    if peer.reader_errors:
                        report['limitations'].append({'readerErrors': peer.reader_errors})
            stop(daemon)
            model.shutdown(); model.server_close()
            report['modelCalls'] = fixture.calls
            report['limitations'].extend(['Local deterministic model fixture; no real model inference.',
                'Production CLI socket transport and shared RPC/event/snapshot/approval components; capture-only subclass.',
                'No CarryOn HTTP/iOS integration or managed daemon discovery tested.',
                'No desktop connection required or created.'])
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
