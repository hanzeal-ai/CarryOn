"""Inline review against a private native home and localhost model."""
import os
import json
import socket
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from run_appserver_regression import wait_until
from carryon.app_server.app_server import AppServer
from carryon.app_server.app_server_bridge import AppServerBridge
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError
from carryon.owner.integration import OwnerBridge
from carryon.owner.manager import OwnerManager
from carryon.sessions.catalog import Catalog
from carryon.sessions.operations import submit
from carryon.store import Journal


class ReviewModel(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        self.server.requests.append({'model': request.get('model'), 'text': request.get('text'),
                                     'inputTail': request.get('input', [])[-3:]})
        output = json.dumps({'findings': [], 'overall_correctness': 'patch is correct',
                             'overall_explanation': 'Isolated fixture has no findings.', 'overall_confidence_score': 1.0})
        item = {'id': 'msg_fixture', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                'content': [{'type': 'output_text', 'text': output, 'annotations': []}]}
        response = {'id': 'resp_fixture', 'object': 'response', 'status': 'completed', 'output': [item],
                    'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13}}
        events = [{'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': []}},
                  {'type': 'response.output_item.added', 'output_index': 0, 'item': {**item, 'status': 'in_progress', 'content': []}},
                  {'type': 'response.output_text.delta', 'item_id': item['id'], 'output_index': 0, 'content_index': 0, 'delta': output},
                  {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                  {'type': 'response.completed', 'response': response}]
        body = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode()
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeReviewIntegration(unittest.TestCase):
    def test_direct_review(self): self.run_case(False)
    def test_owner_review(self): self.run_case(True)

    def run_case(self, owned):
        model = ThreadingHTTPServer(('127.0.0.1', 0), ReviewModel); model.requests = []
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='carryon-native-review-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
                '[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) +
                '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            journal = Journal(root / 'jobs.sqlite'); follower = None; inspector = None
            if owned:
                follower = DesktopIPC('unused'); follower.client_id = 'fixture-desktop'
                class Transport(DesktopIPC):
                    def connect(self):
                        self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                        for ipc in (self, follower):
                            threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
                    def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
                catalog = Catalog(home); manager = OwnerManager(home, root / 'owner', catalog, transport_factory=Transport)
                bridge = OwnerBridge('unused', catalog, journal, owner_directory=root / 'owner')
                bridge.ipc = follower; bridge.enabled = True; bridge.owner_service = manager
                runtime = AppServer(home, runtime_directory=root / 'runtime'); runtime.connect()
            else:
                bridge = AppServerBridge(home, journal); bridge.enable(); runtime = bridge.ipc
            native_events = []; native_replies = []
            original_event = runtime._event; original_rpc = runtime.rpc
            def observe(event):
                method = event.get('method', '')
                if any(key in method.lower() for key in ('turn', 'review', 'task_', 'status')):
                    native_events.append(event)
                original_event(event)
            def rpc(method, params, before_send=None, **kwargs):
                result = original_rpc(method, params, before_send, **kwargs)
                if method == 'review/start': native_replies.append(result)
                return result
            runtime._event = observe; runtime.rpc = rpc
            try:
                thread = runtime.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda write: write())
                tid = thread['id']
                if owned:
                    # Native empty threads are not persisted in the catalog until
                    # their first turn. Adopt the empty baseline, then seed it as
                    # in the fork/edit fixtures before using catalog-backed APIs.
                    manager.adopt(tid, runtime)
                    runtime.start(tid, 'fixture seed', 'app-server', 'seed', lambda write: write())
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid)))
                    wait_until(lambda: bool(catalog.list())); follower.snapshot(tid)
                data = {'action': 'review', 'requestId': 'native-review-once',
                        'target': {'type': 'custom', 'instructions': 'Review fixture only; respond briefly.'}}
                job = submit(bridge, tid, data)
                self.assertEqual(job['state'], 'completed', job)
                self.assertEqual(job['reviewThreadId'], tid)
                if owned:
                    wait_until(lambda: manager.entries[tid].get('suspended') is True)
                    inspector = AppServer(home, runtime_directory=root / 'inspector'); inspector.connect(); inspector.snapshot(tid)
                    reader = inspector
                else:
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid))); reader = runtime
                page = reader.rpc('thread/turns/list', {'threadId': tid, 'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
                turn = next(turn for turn in page['data'] if turn['id'] == job['turnId'])
                self.assertEqual(turn['status'], 'completed', turn)
                self.assertIn('enteredReviewMode', [item['type'] for item in turn['items']])
                self.assertIn('exitedReviewMode', [item['type'] for item in turn['items']])
                self.assertEqual(submit(bridge, tid, data), job)
            except Exception as exc:
                logs = '\n'.join(str(path.relative_to(root)) + '\n' + path.read_text(errors='replace') for path in root.rglob('app-server.log'))
                self.fail(str(exc) + '\nIsolated native diagnostics:\n' + logs + '\nNative state:\n' +
                          json.dumps(runtime.current(tid), default=str, ensure_ascii=False) + '\nLocal model requests:\n' +
                          json.dumps(model.requests[-3:], ensure_ascii=False)[:16000] + '\nNative replies/events:\n' +
                          json.dumps({'replies': native_replies, 'events': native_events}, ensure_ascii=False))
            finally:
                if inspector: inspector.close()
                if follower: follower.close()
                if owned: bridge.shutdown()
                else: bridge.disable()
                runtime.close(); journal.conn.close(); model.shutdown(); model.server_close()
