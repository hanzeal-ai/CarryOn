"""Own a stdio app-server and adapt its public wire to session snapshots.

The home selects native data and credentials; runtime_directory isolates the
process lock and logs. No desktop IPC is used by this transport.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid
from contextlib import suppress

from carryon.desktop_ipc.events import Events
from carryon.sessions.history_cache import NativeSnapshot
from carryon.desktop_ipc.ipc import IPCError
from carryon.paths import private_dir
from carryon.usage import executable


def native_turn(turn):
    return {**turn, 'turnId': turn['id']}


class AppServer:
    protocol = 'codex-app-server'
    supported_operations = {'interrupt', 'steer', 'compact', 'command-approval', 'file-approval',
                            'permissions-approval', 'user-input', 'mcp-response'}
    MAX_FRAME = 32 * 1024 * 1024

    def __init__(self, home, *, runtime_directory=None):
        self.home = Path(home).resolve()
        self.runtime_directory = Path(runtime_directory).resolve() if runtime_directory else self.home
        self.process = None
        self.home_lock = None
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.load_lock = threading.Lock()
        self.pending = {}
        self.response_waiters = {}
        self.session_id = uuid.uuid4().hex
        self.snapshots = {}
        self.following = {}
        self.watchers = {}
        self.loading = {}
        self.events = Events(self)
        self.on_change = lambda: None
        self.on_read = lambda tid, state=None, token=None: None
        self.account_ready = False

    @property
    def connected(self):
        return self.process is not None and self.process.poll() is None

    def connect(self):
        self.session_id = uuid.uuid4().hex
        private_dir(self.runtime_directory)
        self.home_lock = (self.runtime_directory / '.carryon-app-server.lock').open('a+')
        try:
            fcntl.flock(self.home_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (self.runtime_directory / 'app-server.log').open('ab') as log:
                self.process = subprocess.Popen([executable(), 'app-server', '--listen', 'stdio://'],
                    cwd=str(self.home), env=dict(os.environ, CODEX_HOME=str(self.home)),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
            threading.Thread(target=self._reader, args=(self.process,), daemon=True, name='app-server-reader').start()
            self.rpc('initialize', {'clientInfo': {'name': 'carryon', 'version': '1.0'},
                                    'capabilities': {'experimentalApi': True}})
            self._write({'method': 'initialized', 'params': {}})
            account = self.rpc('account/read', {'refreshToken': False})
            self.account_ready = bool(account.get('account')) or account.get('requiresOpenaiAuth') is False
        except Exception:
            self.close()
            raise

    def _write(self, value):
        payload = json.dumps(value, ensure_ascii=False).encode() + b'\n'
        if len(payload) > self.MAX_FRAME:
            raise IPCError('请求过大')
        with self.write_lock:
            if not self.connected:
                raise IPCError('工作区 app-server 已断开')
            self.process.stdin.write(payload)
            self.process.stdin.flush()

    def rpc(self, method, params, before_send=None, timeout_ms=15000):
        identifier = str(uuid.uuid4())
        waiter = {'event': threading.Event()}
        with self.lock:
            self.pending[identifier] = waiter
        attempted = False
        try:
            def write():
                nonlocal attempted
                attempted = True
                self._write({'id': identifier, 'method': method, 'params': params})
            if before_send: before_send(write)
            else: write()
            if not waiter['event'].wait(timeout_ms / 1000):
                raise IPCError('工作区 app-server 响应超时；不会自动重发', uncertain=attempted)
            if 'error' in waiter:
                raise IPCError(waiter['error'], uncertain=attempted)
            response = waiter['response']
            if 'error' in response:
                raise IPCError(response['error'].get('message', 'app-server 拒绝请求'))
            return response.get('result', {})
        except OSError as exc:
            raise IPCError('工作区 app-server 通信失败', uncertain=attempted) from exc
        finally:
            with self.lock:
                self.pending.pop(identifier, None)

    def _reader(self, process):
        try:
            while True:
                line = process.stdout.readline(self.MAX_FRAME + 1)
                if not line or len(line) > self.MAX_FRAME:
                    break
                value = json.loads(line)
                if 'method' not in value:
                    with self.lock:
                        waiter = self.pending.get(value.get('id'))
                        if waiter:
                            waiter['response'] = value
                            waiter['event'].set()
                else:
                    self._event(value)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        finally:
            self.close(expected=process)

    def close(self, expected=None):
        with self.lock:
            if expected is not None and self.process is not expected: return
            process, self.process = self.process, None
            home_lock, self.home_lock = self.home_lock, None
            self.snapshots.clear(); self.following.clear(); self.loading.clear(); self.events.clear()
            for waiter in self.response_waiters.values():
                waiter['error'] = '工作区 app-server 已断开；回复是否处理尚未确认'
                waiter['event'].set()
            self.response_waiters.clear()
            for waiter in self.pending.values():
                waiter['error'] = '工作区 app-server 已断开；已投递请求的结果可能未知'
                waiter['event'].set()
        if process:
            if process.poll() is None:
                with suppress(OSError): process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    with suppress(OSError): process.kill()
                    process.wait(timeout=2)
            with suppress(OSError): process.stdin.close()
            with suppress(OSError): process.stdout.close()
        if home_lock: home_lock.close()
        self.on_change()

    def current(self, tid):
        with self.lock:
            return self.snapshots.get(tid)

    def require_account(self):
        if not self.account_ready:
            raise IPCError('此工作区尚未完成 Codex 登录，请使用该工作区的 CODEX_HOME 登录后重新连接')

    def create_thread(self, params, before_send):
        result = self.rpc('thread/start', params, before_send=before_send)
        thread = result['thread']
        # A new empty thread is not durable yet. Keep this runtime and seed its
        # snapshot from the native response before handing it to the IPC owner.
        with self.lock:
            self._apply({'method': 'thread/started', 'params': {'thread': thread}}, thread['id'])
            state = self.snapshots[thread['id']]
            state['threadMetadata'] = thread
            state['latestThreadSettings'] = {k: v for k, v in result.items() if k in
                ('model', 'reasoningEffort', 'approvalPolicy', 'approvalsReviewer', 'sandboxPolicy')}
            state['latestModel'] = result.get('model')
            state['latestReasoningEffort'] = result.get('reasoningEffort')
        return thread

    def watch(self, tid):
        with self.lock: self.watchers[tid] = self.watchers.get(tid, 0) + 1

    def unwatch(self, tid):
        with self.lock:
            if self.watchers.get(tid, 0) > 1: self.watchers[tid] -= 1
            else: self.watchers.pop(tid, None)

    def snapshot(self, tid):
        # A resume subscribes this client. Serialize hydration while buffering all
        # intervening notifications, then replay them over the initial snapshot.
        with self.load_lock:
            with self.lock:
                current = self.snapshots.get(tid)
                if current is not None and not current.get('_metadataOnly'): return 'app-server', current
                self.loading[tid] = []
            try:
                result = self.rpc('thread/resume', {'threadId': tid, 'excludeTurns': True})
                thread = result['thread']
                turns, cursor = [], None
                while True:
                    page = self.rpc('thread/turns/list', {'threadId': tid, 'cursor': cursor,
                        'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
                    turns.extend(native_turn(turn) for turn in page['data'])
                    cursor = page.get('nextCursor')
                    if not cursor: break
                state = NativeSnapshot({'id': tid, 'title': thread.get('name') or thread.get('preview', ''),
                    'threadMetadata': thread, 'cwd': thread['cwd'], 'turns': turns, 'threadRuntimeStatus': thread['status'], 'requests': [], 'supportedOperations': sorted(self.supported_operations),
                    'latestThreadSettings': {k: v for k, v in result.items() if k in ('model', 'reasoningEffort', 'approvalPolicy')},
                    'latestModel': result.get('model'), 'latestReasoningEffort': result.get('reasoningEffort')})
                with self.lock:
                    if not self.connected: raise IPCError('工作区 app-server 已断开')
                    self.snapshots[tid] = state
                    self.following[tid] = 'app-server'
                    buffered = self.loading.pop(tid, [])
                    for event in buffered: self._apply(event, tid)
                    return 'app-server', self.snapshots[tid]
            finally:
                with self.lock: self.loading.pop(tid, None)

    def sidebar_snapshot(self, tid):
        current = self.current(tid)
        if current is not None: return 'app-server', current
        thread = self.rpc('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
        with self.lock:
            state = self.snapshots.setdefault(tid, NativeSnapshot({'id': tid,
                'title': thread.get('name') or thread.get('preview', ''), 'cwd': thread['cwd'],
                'turns': [], 'requests': [], 'supportedOperations': sorted(self.supported_operations), 'threadRuntimeStatus': thread['status'], '_metadataOnly': True}))
        return 'app-server', state

    def _event(self, event):
        params = event.get('params', {})
        if event['method'] == 'account/updated':
            self.account_ready = bool(params.get('authMode'))
            self.on_change()
            return
        tid = params.get('threadId') or params.get('thread', {}).get('id')
        if 'id' in event and event['method'] not in {
                'item/commandExecution/requestApproval', 'item/fileChange/requestApproval',
                'item/permissions/requestApproval', 'item/tool/requestUserInput', 'mcpServer/elicitation/request'}:
            self._write({'id': event['id'], 'error': {'code': -32601, 'message': 'CarryOn does not support this server request'}})
            return
        with self.lock:
            if tid in self.loading:
                self.loading[tid].append(event)
                return
            self._apply(event, tid)
        self.on_change()

    def _apply(self, event, tid):
        method, params = event['method'], event.get('params', {})
        if method in ('thread/started', 'thread/archived', 'thread/unarchived', 'thread/name/updated'):
            self.events.catalog_revision += 1
        if method == 'serverRequest/resolved':
            waiter = self.response_waiters.get((tid, type(params.get('requestId')), params.get('requestId')))
            if waiter is not None and waiter['sent']:
                waiter['resolved'] = True
                waiter['event'].set()
        old = self.snapshots.get(tid)
        if old is None and method == 'thread/started':
            thread = params['thread']
            self.snapshots[tid] = NativeSnapshot({'id': tid, 'title': thread.get('name') or thread.get('preview', ''),
                'cwd': thread['cwd'], 'turns': [native_turn(t) for t in thread.get('turns', [])],
                'threadRuntimeStatus': thread['status'], 'requests': [], 'supportedOperations': sorted(self.supported_operations)})
            self.following[tid] = 'app-server'
            return
        if old is None: return
        state = NativeSnapshot(old)
        if 'id' in event:
            state['requests'] = [*old.get('requests', []), event]
        elif method == 'serverRequest/resolved':
            state['requests'] = [r for r in old['requests'] if r['id'] != params.get('requestId')]
        elif method == 'thread/status/changed': state['threadRuntimeStatus'] = params['status']
        elif method == 'thread/name/updated': state['title'] = params.get('threadName') or ''
        elif method == 'thread/settings/updated': state['latestThreadSettings'] = params['threadSettings']
        elif method in ('turn/started', 'turn/completed'):
            turn = native_turn(params['turn'])
            previous = next((t for t in old['turns'] if t['turnId'] == turn['turnId']), None)
            if previous and (not params['turn'].get('items') or params['turn'].get('itemsView') in ('summary', 'notLoaded')):
                # A completion summary is not a replacement for streamed items.
                # Apply the native updates by id without losing omitted inputs
                # or tool calls.
                updates = {item['id']: item for item in turn['items']}
                items = [updates.pop(item['id'], item) for item in previous['items']]
                turn.update(items=items + list(updates.values()))
            state['turns'] = [turn if t['turnId'] == turn['turnId'] else t for t in old['turns']]
            if previous is None: state['turns'].append(turn)
        elif method.startswith('item/'):
            turns = list(old['turns'])
            index = next((i for i, t in enumerate(turns) if t['turnId'] == params.get('turnId')), None)
            if index is None: return
            turn = dict(turns[index]); items = list(turn['items']); turn['items'] = items
            if method in ('item/started', 'item/completed'):
                item = params['item']
                pos = next((i for i, v in enumerate(items) if v['id'] == item['id']), None)
                if pos is None: items.append(item)
                else: items[pos] = item
            elif method in ('item/agentMessage/delta', 'item/plan/delta', 'item/commandExecution/outputDelta'):
                pos = next((i for i, v in enumerate(items) if v['id'] == params.get('itemId')), None)
                if pos is None: return
                field = 'aggregatedOutput' if method == 'item/commandExecution/outputDelta' else 'text'
                items[pos] = {**items[pos], field: (items[pos].get(field) or '') + params['delta']}
            else: return
            turns[index] = turn; state['turns'] = turns
        else: return
        self.snapshots[tid] = state

    def start(self, tid, text, owner, client_message_id, before_send, images=None):
        self.require_account()
        result = self.rpc('turn/start', {'threadId': tid, 'clientUserMessageId': client_message_id,
            'input': ([{'type': 'text', 'text': text, 'text_elements': []}] if text else []) +
                     [{'type': 'image', 'url': url} for url in (images or [])]}, before_send)
        return result['turn']

    def request(self, method, params, version=0, target=None, before_send=None, timeout_ms=15000):
        tid = params.get('conversationId')
        if method == 'thread-follower-interrupt-turn':
            result = self.rpc('turn/interrupt', {'threadId': tid, 'turnId': params['expectedTurnId']}, before_send)
        elif method == 'thread-follower-steer-turn':
            state = self.current(tid)
            active = next((t for t in reversed(state['turns']) if t['status'] == 'inProgress'), None)
            if active is None: raise IPCError('执行轮次已改变')
            result = self.rpc('turn/steer', {'threadId': tid, 'expectedTurnId': active['turnId'], 'input': params['input']}, before_send)
        elif method == 'thread-follower-compact-thread':
            result = self.rpc('thread/compact/start', {'threadId': tid}, before_send)
        elif method in ('thread-follower-command-approval-decision', 'thread-follower-file-approval-decision',
                         'thread-follower-permissions-request-approval-response', 'thread-follower-submit-user-input',
                         'thread-follower-submit-mcp-server-elicitation-response'):
            return self.respond(tid, params, before_send, timeout_ms)
        else:
            raise IPCError('独立 app-server 暂不支持此桌面专属操作')
        return {'result': result}

    def respond(self, tid, params, before_send, timeout_ms):
        request_id = params['requestId']
        key = (tid, type(request_id), request_id)
        waiter = {'event': threading.Event(), 'sent': False}
        with self.lock:
            if key in self.response_waiters:
                raise IPCError('此原生请求的回复已发送，请先核对结果')
            if len(self.response_waiters) >= 500:
                raise IPCError('待核对回复过多，请先核对已有请求')
            self.response_waiters[key] = waiter
        try:
            def write():
                waiter['sent'] = True
                self._write({'id': request_id, 'result': params.get('response', {'decision': params.get('decision')})})
            if before_send: before_send(write)
            else: write()
            if not waiter['event'].wait(timeout_ms / 1000):
                raise IPCError('回复已发送，原生尚未确认请求已处理；不会自动重发', uncertain=True)
            if 'error' in waiter:
                raise IPCError(waiter['error'], uncertain=waiter['sent'])
            return {'result': {}, 'evidence': 'native-server-request-resolved'}
        except IPCError as exc:
            if not exc.uncertain:
                waiter['sent'] = False
            raise
        except OSError as exc:
            raise IPCError('回复写入失败，结果待核对', uncertain=waiter['sent']) from exc
        finally:
            with self.lock:
                if not waiter['sent'] and self.response_waiters.get(key) is waiter:
                    self.response_waiters.pop(key, None)

    def response_resolved(self, tid, request_id):
        with self.lock:
            return self.response_waiters.get((tid, type(request_id), request_id), {}).get('resolved') is True

    def forget_response(self, tid, request_id):
        with self.lock:
            self.response_waiters.pop((tid, type(request_id), request_id), None)
