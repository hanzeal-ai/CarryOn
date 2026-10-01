"""An inline native review is one authorized, non-replayed operation."""
from contextlib import nullcontext
import json
from pathlib import Path

from carryon.contracts import validate
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.history_cache import NativeSnapshot

CONTRACT = json.loads(Path(__file__).with_name('review_contract.json').read_text())


def invalidate(runtime, tid, identity):
    with runtime.lock:
        state = runtime.current(tid)
        if state is not None and (runtime.process, runtime.session_id, state.get('cwd')) == identity:
            runtime.snapshots[tid] = NativeSnapshot({**state, '_metadataOnly': True,
                'threadRuntimeStatus': {'type': 'notLoaded'}})
    runtime.on_change()


def request(tid, data):
    if set(data) - {'requestId', 'action', 'target'}: raise ValueError('审查只接受 target')
    value = {'threadId': tid, 'delivery': 'inline', 'target': data.get('target')}
    validate(value, CONTRACT)
    for key, item in value['target'].items():
        if key != 'type' and item is not None and (not item.strip() or len(item) > (16000 if key == 'instructions' else 500)):
            raise ValueError('审查目标字段为空或过长')
    return value


def dispatch(bridge, ipc, generation, job, data, authorize):
    tid = job['threadId']; attempted = False; replied = False; runtime = None; submitted = set()
    def authorized():
        bridge.check_generation(ipc, generation)
        bridge.assert_target(tid)
        if authorize: authorize()
    try:
        params = request(tid, data)
        if job.get('sideParentId'): raise IPCError('临时聊天不支持仓库审查')
        if getattr(ipc, 'protocol', None) == 'codex-app-server':
            session = nullcontext((ipc, lambda write: write()))
        elif hasattr(bridge, 'native_session'):
            session = bridge.native_session(tid, authorized, loaded_only=True, submitted_turns=submitted)
        else: raise IPCError('当前桌面会话不支持原生仓库审查')
        with session as target:
            if target is None: raise IPCError('此操作需要已加载的原生会话')
            runtime, owner_guard = target
            runtime.require_account()
            with runtime._queue_lock(tid):
                state = runtime.current(tid)
                if not state or state.get('_metadataOnly') or not runtime.queue_idle(state):
                    raise IPCError('审查需要已加载且空闲的原生会话')
                identity = (runtime.process, runtime.session_id, state.get('cwd'))
                if runtime.queue_snapshot(tid, refresh=True): raise IPCError('请先处理排队消息再审查')
                def guarded(write):
                    nonlocal attempted
                    with bridge.lock:
                        authorized()
                        def checked():
                            nonlocal attempted
                            with runtime.lock:
                                current = runtime.current(tid)
                                if (not current or current.get('_metadataOnly') or not runtime.connected
                                        or not runtime.queue_idle(current)
                                        or (runtime.process, runtime.session_id, current.get('cwd')) != identity):
                                    raise IPCError('审查前原生会话状态已改变')
                                bridge.journal.update(job['id'], state='dispatching')
                                attempted = True
                                write()
                        owner_guard(checked)
                try:
                    result = runtime.rpc('review/start', params, guarded)
                    replied = True
                    if result.get('reviewThreadId') != tid or not isinstance(result.get('turn', {}).get('id'), str) or not result['turn']['id']:
                        raise IPCError('原生审查回执身份不匹配', uncertain=True)
                    with bridge.lock:
                        authorized()
                        def confirm():
                            with runtime.lock:
                                current = runtime.current(tid)
                                if (not current or not runtime.connected or
                                        (runtime.process, runtime.session_id, current.get('cwd')) != identity):
                                    raise IPCError('审查回执所属连接已改变', uncertain=True)
                                runtime.record_started(tid, result['turn'])
                                submitted.add(result['turn']['id'])
                                bridge.journal.update(job['id'], state='completed', turnId=result['turn']['id'],
                                    reviewThreadId=tid, result=result, evidence='native-review-start')
                        owner_guard(confirm)
                except Exception as exc:
                    if attempted and (replied or not isinstance(exc, IPCError) or exc.uncertain):
                        # Invalidate before the Owner lifetime guard is released.
                        invalidate(runtime, tid, identity)
                    raise
    except Exception as exc:
        uncertain = attempted and (replied or not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
    bridge.notify()
