"""Transport-independent public RPC, projections and request acknowledgement."""
import json
from pathlib import Path
import threading
import uuid
import weakref

from carryon.codex_protocol.events import ProjectionEvents
from carryon.sessions.history_cache import NativeSnapshot
from carryon.errors import IPCError
from carryon.contracts import SCHEMAS


def native_turn(turn):
    return {**turn, 'turnId': turn['id']}


def thread_settings(result):
    keys = ('model', 'approvalPolicy', 'approvalsReviewer', 'sandboxPolicy', 'permissions',
            'serviceTier', 'collaborationMode', 'cwd', 'disabledPluginIds', 'personality', 'activePermissionProfile')
    return {**{key: result[key] for key in keys if key in result},
            **({'sandboxPolicy': result['sandbox']} if 'sandbox' in result else {}),
            'effort': result.get('reasoningEffort')}


class ProtocolClient:
    protocol = 'codex-app-server'
    execution_backend = 'app-server'
    started_is_subscribed = False
    supported_settings = sorted(set(SCHEMAS['settings']['properties']) - {'threadId', 'multiAgentMode', 'activePermissionProfile'})
    supported_operations = {'archive', 'rename', 'interrupt', 'steer', 'compact', 'settings', 'edit', 'fork', 'side-create', 'review', 'resume', 'queue-add', 'queue-edit', 'queue-delete', 'queue-reorder', 'queue-resume', 'command-approval', 'file-approval',
                            'permissions-approval', 'user-input', 'mcp-response', 'goal-set', 'goal-pause', 'goal-clear', 'voice-start', 'voice-stop'}
    MAX_FRAME = 32 * 1024 * 1024

    def __init__(self, home, *, runtime_directory=None):
        self.home = Path(home).resolve()
        self.runtime_directory = Path(runtime_directory).resolve() if runtime_directory else self.home
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
        self.events = ProjectionEvents()
        self.on_change = lambda: None
        self.on_read = lambda tid, state=None, token=None: None
        self.account_ready = False
        self.queue_locks = weakref.WeakValueDictionary()
        self.review_refreshing = {}
        self.voice_channels = {}

    def initialize(self):
        self.rpc('initialize', {'clientInfo': {'name': 'carryon', 'version': '1.0'},
                                'capabilities': {'experimentalApi': True}})
        self._write({'method': 'initialized', 'params': {}})
        account = self.rpc('account/read', {'refreshToken': False})
        if not isinstance(account, dict):
            raise IPCError('Codex 账号响应格式无效')
        self.account_ready = bool(account.get('account')) or account.get('requiresOpenaiAuth') is False
        return account

    def receive(self, value):
        if 'method' in value:
            self._event(value)
        else:
            with self.lock:
                waiter = self.pending.get(value.get('id'))
                if waiter:
                    waiter['response'] = value
                    waiter['event'].set()

    def disconnected(self):
        # Called under the transport's lock after detaching its connection.
        self.account_ready = False
        self.voice_channels.clear(); self.snapshots.clear(); self.following.clear(); self.loading.clear(); self.events.clear()
        for waiter in self.response_waiters.values():
            waiter['error'] = 'Codex 连接已断开；回复是否处理尚未确认'
            waiter['event'].set()
        self.response_waiters.clear()
        for waiter in self.pending.values():
            waiter['error'] = 'Codex 连接已断开；已投递请求的结果可能未知'
            waiter['event'].set()

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
            state.pop('_metadataOnly', None)
            self.following[thread['id']] = 'app-server'
            state['threadMetadata'] = thread
            state['latestThreadSettings'] = thread_settings(result)
            state['latestModel'] = result.get('model')
            state['latestReasoningEffort'] = result.get('reasoningEffort')
        from carryon.codex_protocol.goals import read
        read(self, thread['id'])
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
                from carryon.codex_protocol.goals import value
                goal = value(self.rpc('thread/goal/get', {'threadId': tid}), tid)
                state = NativeSnapshot({'id': tid, 'executionBackend': self.execution_backend, 'title': thread.get('name') or thread.get('preview', ''),
                    'threadMetadata': thread, 'cwd': thread['cwd'], 'turns': turns, 'threadRuntimeStatus': thread['status'], 'requests': [], 'supportedOperations': sorted(self.supported_operations),
                    'queueBackend': 'app-server', 'supportsSkills': True, 'supportsMentions': True, 'supportsFileReferences': True, 'supportedSettings': self.supported_settings, 'latestThreadSettings': thread_settings(result),
                    'latestModel': result.get('model'), 'latestReasoningEffort': result.get('reasoningEffort'),
                    'supportsBackgroundTerminals': True, 'supportsGoal': True, 'threadGoal': goal, '_goalUnknown': False})
                with self.lock:
                    if not self.connected: raise IPCError('工作区 app-server 已断开')
                    self.snapshots[tid] = state
                    self.following[tid] = 'app-server'
                    buffered = self.loading.pop(tid, [])
                    for event in buffered: self._apply(event, tid)
                    return 'app-server', self.snapshots[tid]
            finally:
                with self.lock: self.loading.pop(tid, None)

    def read_turns(self, tid):
        """Read persisted turn evidence without resuming a task or its goal."""
        result, cursor, seen = [], None, set()
        while True:
            page = self.rpc('thread/turns/list', {'threadId': tid, 'cursor': cursor,
                'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
            result.extend(native_turn(turn) for turn in page['data'])
            cursor = page.get('nextCursor')
            if not cursor: return result
            if cursor in seen: raise IPCError('原生历史分页游标重复')
            seen.add(cursor)

    def refresh_snapshot(self, tid):
        # Reading never resumes unloaded conversations. Loaded histories continue
        # to receive ordered app-server notifications on this connection.
        with self.lock: before = self.snapshots.get(tid)
        thread = self.rpc('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
        with self.lock:
            previous = self.snapshots.get(tid)
            # The reader can apply newer notifications (or hydration can finish)
            # before this RPC caller runs again. Never overwrite that projection
            # with an older read response. NativeSnapshot changes by replacement.
            if previous is not None and previous is not before:
                return 'app-server', previous
            state = NativeSnapshot({**(previous or {'id': tid, 'turns': [], 'requests': [], '_metadataOnly': True}),
                'executionBackend': self.execution_backend,
                'title': thread.get('name') or thread.get('preview', ''), 'cwd': thread['cwd'],
                'threadMetadata': thread, 'threadRuntimeStatus': thread['status']})
            self.snapshots[tid] = state
        return 'app-server', state

    def sidebar_snapshot(self, tid):
        current = self.current(tid)
        if current is not None: return 'app-server', current
        thread = self.rpc('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
        with self.lock:
            state = self.snapshots.setdefault(tid, NativeSnapshot({'id': tid, 'executionBackend': self.execution_backend,
                'title': thread.get('name') or thread.get('preview', ''), 'cwd': thread['cwd'],
                'turns': [], 'requests': [], 'supportsSkills': False, 'supportedSettings': self.supported_settings, 'supportedOperations': sorted(self.supported_operations - {'review'}), 'threadRuntimeStatus': thread['status'], '_metadataOnly': True}))
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
        if event['method'].startswith('thread/realtime/'):
            from carryon.codex_protocol.realtime_voice import event as voice_event
            with self.lock: changed = voice_event(self, tid, event['method'], params)
            if changed: self.on_change()
            return
        with self.lock:
            if tid in self.loading:
                self.loading[tid].append(event)
                return
            self._apply(event, tid)
        if event['method'] == 'turn/completed':
            from carryon.codex_protocol.review_history import schedule
            schedule(self, tid, params['turn']['id'])
        self.on_change()

    def _apply(self, event, tid):
        method, params = event['method'], event.get('params', {})
        if method in ('thread/started', 'thread/archived', 'thread/unarchived', 'thread/name/updated',
                      'thread/deleted', 'project/changed', 'thread/project/updated'):
            self.events.catalog_revision += 1
        if method == 'serverRequest/resolved':
            waiter = self.response_waiters.get((tid, type(params.get('requestId')), params.get('requestId')))
            if waiter is not None and waiter['sent']:
                waiter['resolved'] = True
                waiter['event'].set()
        old = self.snapshots.get(tid)
        if old is None and method == 'thread/started':
            thread = params['thread']
            self.snapshots[tid] = NativeSnapshot({'id': tid, 'executionBackend': self.execution_backend, 'title': thread.get('name') or thread.get('preview', ''),
                '_metadataOnly': not self.started_is_subscribed, 'threadMetadata': thread, 'cwd': thread['cwd'], 'turns': [native_turn(t) for t in thread.get('turns', [])],
                'threadRuntimeStatus': thread['status'], 'requests': [], 'queueBackend': 'app-server', 'supportsSkills': True, 'supportsMentions': True, 'supportsFileReferences': True, 'supportsBackgroundTerminals': True, 'supportsGoal': True, '_goalUnknown': True, 'threadGoal': None, 'supportedSettings': self.supported_settings, 'supportedOperations': sorted(self.supported_operations)})
            if self.started_is_subscribed: self.following[tid] = 'app-server'
            return
        if old is None: return
        state = NativeSnapshot(old)
        if 'id' in event:
            state['requests'] = [*old.get('requests', []), event]
        elif method == 'serverRequest/resolved':
            state['requests'] = [r for r in old['requests'] if r['id'] != params.get('requestId')]
        elif method == 'thread/status/changed': state['threadRuntimeStatus'] = params['status']
        elif method == 'thread/name/updated': state['title'] = params.get('threadName') or ''
        elif method in ('thread/goal/updated', 'thread/goal/cleared'):
            from carryon.codex_protocol.goals import value
            try:
                state['threadGoal'] = value({'goal': params.get('goal') if method.endswith('/updated') else None}, tid)
                state['_goalUnknown'] = False
            except IPCError:
                state['_goalUnknown'] = True
            state['_goalRevision'] = old.get('_goalRevision', 0) + 1
        elif method == 'thread/settings/updated':
            state['latestThreadSettings'] = params['threadSettings']
            state['latestModel'] = params['threadSettings'].get('model')
            state['latestReasoningEffort'] = params['threadSettings'].get('effort')
            if params['threadSettings'].get('cwd'):
                state['cwd'] = params['threadSettings']['cwd']
                if 'threadMetadata' in state: state['threadMetadata'] = {**state['threadMetadata'], 'cwd': state['cwd']}
        elif method == 'thread/tokenUsage/updated':
            state['latestTokenUsageInfo'] = params['tokenUsage']
        elif method == 'thread/queue/changed':
            state.pop('nativeQueue', None)
        elif method == 'turn/diff/updated':
            if not isinstance(params.get('diff'), str): return
            state['turns'] = [{**turn, 'diff': params['diff']} if turn['turnId'] == params.get('turnId') else turn
                              for turn in old['turns']]
        elif method in ('turn/started', 'turn/completed'):
            turn = native_turn(params['turn'])
            if method == 'turn/started': state['threadRuntimeStatus'] = {'type': 'active', 'activeFlags': []}
            previous = next((t for t in old['turns'] if t['turnId'] == turn['turnId']), None)
            if previous and 'diff' not in turn and 'diff' in previous:
                turn['diff'] = previous['diff']
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

    def record_started(self, tid, turn):
        with self.lock:
            state = self.current(tid)
            if state is not None and not any(t['turnId'] == turn['id'] for t in state['turns']):
                self._event({'method': 'turn/started', 'params': {'threadId': tid, 'turn': turn}})

    def start_turn(self, tid, request, before_send=None):
        self.require_account()
        with self._queue_lock(tid):
            from carryon.sessions.skills import guard_inputs
            before_send = guard_inputs(self, tid, request['input'], before_send)
            def guarded(write):
                def checked():
                    with self.lock:
                        if not self.queue_idle(self.current(tid)): raise IPCError('会话不再空闲')
                        write()
                if before_send: before_send(checked)
                else: checked()
            result = self.rpc('turn/start', request, guarded)
            self.record_started(tid, result['turn'])
            return result

    def start(self, tid, text, owner, client_message_id, before_send, images=None, skills=None, mentions=None):
        from carryon.sessions.skills import inputs
        from carryon.sessions.mentions import inputs as mention_inputs
        return self.start_turn(tid, {'threadId': tid, 'clientUserMessageId': client_message_id,
            'input': ([{'type': 'text', 'text': text, 'text_elements': []}] if text else []) +
                     [{'type': 'image', 'url': url} for url in (images or [])] + inputs(skills) + mention_inputs(mentions)}, before_send)['turn']

    def request(self, method, params, version=0, target=None, before_send=None, timeout_ms=15000):
        tid = params.get('conversationId')
        if method == 'thread-follower-interrupt-turn':
            result = self.rpc('turn/interrupt', {'threadId': tid, 'turnId': params['expectedTurnId']}, before_send)
        elif method == 'thread-follower-steer-turn':
            from carryon.sessions.skills import guard_inputs
            before_send = guard_inputs(self, tid, params['input'], before_send)
            state = self.current(tid)
            active = next((t for t in reversed(state['turns']) if t['status'] == 'inProgress'), None)
            if active is None: raise IPCError('执行轮次已改变')
            result = self.rpc('turn/steer', {'threadId': tid, 'expectedTurnId': active['turnId'], 'input': params['input']}, before_send)
        elif method == 'thread-follower-compact-thread':
            result = self.rpc('thread/compact/start', {'threadId': tid}, before_send)
        elif method == 'thread-follower-update-thread-settings':
            from carryon.contracts import settings
            values = settings(params.get('threadSettings'), tid)
            if 'activePermissionProfile' in values:
                raise IPCError('app-server 不支持桌面权限配置标识')
            self.rpc('thread/settings/update', {'threadId': tid, **values}, before_send)
            result = {'applied': True}
        elif method == 'thread-follower-set-queued-follow-ups-state':
            from carryon.codex_protocol.queue import replace
            from carryon.contracts import digest
            with self._queue_lock(tid):
                state = self.current(tid) or {}
                expected = params.get('expectedQueueFingerprint')
                if expected is None and 'nativeQueue' in state: expected = digest(state['nativeQueue'])
                result = replace(self, tid, params['state'][tid], expected, before_send)
                # A confirmed mutation stays confirmed if a later refresh fails.
                with self.lock:
                    state = self.current(tid)
                    if state is not None:
                        updated = dict(state); updated.pop('nativeQueue', None)
                        self.snapshots[tid] = NativeSnapshot(updated)
        elif method == 'thread-follower-start-turn':
            request = params['turnStart']['request']
            if request != {'threadId': tid, 'input': []}: raise IPCError('无效继续执行请求')
            result = self.start_turn(tid, request, before_send)
        elif method in ('thread-follower-command-approval-decision', 'thread-follower-file-approval-decision',
                         'thread-follower-permissions-request-approval-response', 'thread-follower-submit-user-input',
                         'thread-follower-submit-mcp-server-elicitation-response'):
            return self.respond(tid, params, before_send, timeout_ms)
        else:
            raise IPCError('独立 app-server 暂不支持此桌面专属操作')
        return {'result': result}

    def _queue_lock(self, tid):
        with self.lock: return self.queue_locks.setdefault(tid, threading.RLock())

    @staticmethod
    def queue_idle(state):
        return bool(state and not state.get('requests') and state['threadRuntimeStatus']['type'] == 'idle'
                    and not any(t['status'] == 'inProgress' for t in state['turns']))

    def queue_snapshot(self, tid, refresh=False):
        from carryon.codex_protocol.queue import messages
        from copy import deepcopy
        with self._queue_lock(tid):
            state = self.current(tid)
            rows = state.get('nativeQueue') if state is not None and not refresh else None
            if rows is None:
                # A notification racing the read invalidates the cache, never writes it back.
                before = self.current(tid)
                rows = messages(self, tid)
                with self.lock:
                    state = self.current(tid)
                    if state is before and state is not None:
                        self.snapshots[tid] = NativeSnapshot({**state, 'nativeQueue': rows, 'queueBackend': 'app-server'})
            result = deepcopy(rows)
            if self.queue_idle(self.current(tid)):
                for row in result: row['pausedReason'] = '等待继续'
            return result

    def queue_busy(self, tid):
        state = self.current(tid)
        return state is None or 'nativeQueue' not in state or bool(state['nativeQueue'])

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
