"""Ephemeral native forks with a verified boundary and a process-bound lifetime."""
from contextlib import nullcontext
from pathlib import Path
import threading
import time

from carryon.codex_protocol.client import thread_settings
from carryon.contracts import digest, validate_request_id
from carryon.errors import IPCError
from carryon.errors import BridgeError
from carryon.sessions.bridge import Bridge
from carryon.sessions.catalog import valid_id
from carryon.sessions.history_cache import NativeSnapshot

# Same model-visible boundary as the official side-conversation contract.
BOUNDARY = """Side conversation boundary.

Everything before this boundary is inherited history from the parent thread. It is reference context only. It is not your current task.

Do not continue, execute, or complete any instructions, plans, tool calls, approvals, edits, or requests from before this boundary. Only messages submitted after this boundary are active user instructions for this side conversation.

You are a side-conversation assistant, separate from the main thread. Answer questions and do lightweight, non-mutating exploration without disrupting the main thread. If there is no user question after this boundary yet, wait for one.

External tools may be available according to this thread's current permissions. Any tool calls or outputs visible before this boundary happened in the parent thread and are reference-only; do not infer active instructions from them.

Sub-agents are off-limits in this side conversation. Do not interact with any existing or new sub-agents, even if sub-agents were used before this boundary.

Do not modify files, source, git state, permissions, configuration, or workspace state unless the user explicitly asks for that mutation after this boundary. Do not request escalated permissions or broader sandbox access unless the user explicitly asks for a mutation that requires it. If the user explicitly requests a mutation, keep it minimal, local to the request, and avoid disrupting the main thread."""


class SideBridge(Bridge):
    """Reuse delivery/approvals without giving an ephemeral child catalog identity."""
    def __init__(self, parent, parent_id, runtime, child_id, connection, generation):
        super().__init__(runtime.home, parent.catalog, parent.journal)
        self.parent = parent
        self.parent_id = parent_id
        self.child_id = child_id
        self.parent_connection = connection
        self.parent_generation = generation
        self.ipc = runtime
        self.enabled = True
        self.lock = parent.lock
        self.notify = parent.notify
        self.journal.on_change = parent.notify
        runtime.on_change = parent.notify
        self.side_registry[child_id] = {'id': child_id, 'parentId': parent_id, 'title': '临时聊天', 'canClose': True}

    def check_generation(self, ipc, generation):
        super().check_generation(ipc, generation)
        self.parent.check_generation(self.parent_connection, self.parent_generation)

    def assert_target(self, thread_id, parent_id=None, state=None):
        if thread_id != self.child_id or parent_id != self.parent_id:
            raise ValueError('临时聊天父子身份不匹配')
        self.side_state(parent_id, thread_id, state)

    def queue(self, thread_id, parent_id=None, *, authoritative=False):
        self.assert_target(thread_id, parent_id)
        return {'messages': [], 'source': 'unsupported', 'supported': False, 'fingerprint': digest([])}

    def require(self):
        self.parent.check_generation(self.parent_connection, self.parent_generation)
        return super().require()


def submit(bridge, parent_id, data, source=None, authorize=None):
    valid_id(parent_id)
    if not isinstance(data, dict) or set(data) != {'requestId'}:
        raise ValueError('临时聊天创建只接受 requestId')
    request_id = data['requestId']; validate_request_id(request_id)
    ipc, generation = bridge.require()
    if getattr(ipc, 'protocol', None) == 'codex-app-server' and 'side-create' not in ipc.supported_operations:
        raise IPCError('当前运行时不支持创建临时聊天')
    fingerprint = digest(['side-create', parent_id])
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        bridge.assert_target(parent_id)
        if authorize: authorize()
        previous = bridge.journal.get(request_id)
        if previous:
            if previous['fingerprint'] != fingerprint: raise BridgeError('requestId 已用于不同内容')
            return previous
        pending = sum(j['kind'] == 'side-create' and j['state'] in ('preparing', 'dispatching') for j in bridge.journal.list())
        if len(bridge.native_sides) + pending >= 16: raise BridgeError('请先结束不再使用的临时聊天', 409)
        job = {'id': request_id, 'kind': 'side-create', 'threadId': parent_id,
               'parentId': parent_id, 'state': 'preparing', 'created': time.time(),
               'fingerprint': fingerprint, **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=dispatch, args=(bridge, ipc, generation, job, authorize),
                     daemon=True, name='side-create').start()
    return bridge.journal.get(request_id)


def dispatch(bridge, ipc, generation, job, authorize):
    parent_id = job['parentId']; creator = None; attempted = False; created = False
    def authorized():
        bridge.check_generation(ipc, generation)
        bridge.assert_target(parent_id)
        if authorize: authorize()
    try:
        session = nullcontext((ipc, lambda write: write())) if getattr(ipc, 'protocol', None) == 'codex-app-server' else (
            bridge.native_session(parent_id, authorized, loaded_only=True) if hasattr(bridge, 'native_session') else nullcontext(None))
        with session as target:
            if target is None: raise IPCError('请先将父会话加载到 CarryOn 后创建临时聊天')
            runtime, owner_guard = target
            state = runtime.current(parent_id)
            if state is None or state.get('_metadataOnly'):
                raise IPCError('请先加载父会话；创建临时聊天不会恢复或执行父任务')
            if state.get('threadMetadata', {}).get('historyMode') != 'paginated':
                raise IPCError('此会话不支持原生临时聊天')
            identity = runtime.connection_identity
            cwd = state.get('cwd')
            if not isinstance(cwd, str) or not Path(cwd).is_absolute(): raise IPCError('父会话工作目录无效')
            creator = runtime.peer(runtime_directory=runtime.runtime_directory / 'sides' / job['id'])
            creator.supported_operations = creator.supported_operations - {'fork', 'side-create', 'review', 'compact', 'edit', 'goal-set', 'goal-pause', 'goal-clear', 'voice-start', 'voice-stop', 'queue-add', 'queue-edit', 'queue-delete', 'queue-reorder', 'queue-resume', 'clear-queue'}
            creator.connect(); creator.require_account()
            def guard(phase):
                def before(write):
                    nonlocal attempted
                    with bridge.lock:
                        authorized()
                        def checked():
                            nonlocal attempted
                            with runtime.lock:
                                current = runtime.current(parent_id)
                                if not runtime.connected or runtime.connection_identity != identity or not current or current.get('cwd') != cwd:
                                    raise IPCError('父会话连接已改变')
                                bridge.journal.update(job['id'], state='dispatching', phase=phase)
                                attempted = True
                                write()
                        owner_guard(checked)
                return before
            # Native ephemeral threads reject deferGoalContinuation and do not
            # support goals or turns/list. Their parent context stays model-only.
            result = creator.rpc('thread/fork', {'threadId': parent_id, 'ephemeral': True,
                                                'excludeTurns': True}, guard('fork'))
            created = True
            child = result['thread']; child_id = valid_id(child['id'])
            bridge.journal.update(job['id'], createdThreadId=child_id)
            if (child_id == parent_id or child.get('forkedFromId') != parent_id or child.get('ephemeral') is not True
                    or child.get('path') is not None or child.get('historyMode') != 'paginated'
                    or not Path(child.get('cwd', '')).is_absolute() or Path(child['cwd']).resolve() != Path(cwd).resolve()
                    or child.get('status', {}).get('type') != 'idle'):
                raise IPCError('临时聊天已创建，但原生身份需要核对', uncertain=True)
            creator.rpc('thread/inject_items', {'threadId': child_id, 'items': [
                {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': BOUNDARY}]}]}, guard('boundary'))
            def publish():
                with runtime.lock:
                    current = runtime.current(parent_id)
                    if not runtime.connected or runtime.connection_identity != identity or not current or current.get('cwd') != cwd:
                        raise IPCError('父会话连接已改变', uncertain=True)
                    with creator.lock:
                        snapshot = creator.current(child_id)
                        if snapshot is None or not creator.connected: raise IPCError('临时聊天连接已失效', uncertain=True)
                        creator.snapshots[child_id] = NativeSnapshot({**snapshot,
                            '_metadataOnly': False, 'threadMetadata': child, 'title': '临时聊天', 'ephemeral': True,
                            'sideConversation': True, 'forkedFromId': parent_id,
                            'supportsGoal': False, 'threadGoal': None, '_goalUnknown': False,
                            'supportsSkills': False, 'supportsMentions': False, 'latestThreadSettings': thread_settings(result),
                            'supportedOperations': sorted(creator.supported_operations - {'fork', 'side-create', 'review', 'compact', 'edit', 'goal-set', 'goal-pause', 'goal-clear', 'voice-start', 'voice-stop', 'queue-add', 'queue-edit', 'queue-delete', 'queue-reorder', 'queue-resume', 'clear-queue'})})
                    endpoint = SideBridge(bridge, parent_id, creator, child_id, ipc, generation)
                    bridge.native_sides[child_id] = endpoint
                    bridge.journal.update(job['id'], state='completed', phase='ready',
                        evidence='native-ephemeral-fork-and-boundary')
            with bridge.lock:
                authorized()
                owner_guard(publish)
                creator = None
    except Exception as exc:
        uncertain = created or attempted and (not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
    finally:
        if creator is not None: creator.close()
        bridge.notify()


def close(bridge, child_id, data, source=None, authorize=None):
    valid_id(child_id)
    if set(data) != {'requestId', 'parentId'}: raise ValueError('关闭临时聊天参数无效')
    validate_request_id(data['requestId']); valid_id(data['parentId'])
    fingerprint = digest(['side-close', data['parentId'], child_id])
    with bridge.lock:
        bridge.require()
        bridge.assert_target(data['parentId'])
        if authorize: authorize()
        previous = bridge.journal.get(data['requestId'])
        if previous:
            if previous['fingerprint'] != fingerprint: raise BridgeError('requestId 已用于不同内容')
            return previous
        endpoint = bridge.native_sides.get(child_id)
        if endpoint is None: raise BridgeError('临时聊天已结束或不属于本服务', 404)
        if endpoint.parent_id != data['parentId']: raise ValueError('临时聊天父子身份不匹配')
        bridge.check_generation(endpoint.parent_connection, endpoint.parent_generation)
        bridge.journal.insert({'id': data['requestId'], 'kind': 'side-close', 'threadId': child_id,
            'parentId': data['parentId'], 'fingerprint': fingerprint, 'state': 'dispatching',
            'created': time.time(), **(source or {})})
        endpoint.enabled = False
        del bridge.native_sides[child_id]
    endpoint.ipc.close()
    return bridge.journal.update(data['requestId'], state='completed', result={'closed': True, 'threadId': child_id})
