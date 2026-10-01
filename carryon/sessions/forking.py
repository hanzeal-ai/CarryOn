"""Fork persisted native history once, without starting a prompt or goal."""
from contextlib import nullcontext
import threading
import time
from pathlib import Path

from carryon.app_server.app_server import AppServer
from carryon.contracts import digest, validate_request_id
from carryon.desktop_ipc.ipc import IPCError
from carryon.errors import BridgeError
from carryon.sessions.catalog import valid_id


def submit(bridge, tid, data, source=None, authorize=None):
    valid_id(tid)
    if not isinstance(data, dict) or set(data) - {'requestId', 'lastTurnId'}:
        raise ValueError('分叉只接受 requestId 和可选 lastTurnId')
    request_id = data.get('requestId'); validate_request_id(request_id)
    last = data.get('lastTurnId')
    if last is not None and (not isinstance(last, str) or not last or len(last) > 200):
        raise ValueError('分叉轮次无效')
    ipc, generation = bridge.require()
    fingerprint = digest(['fork', tid, last])
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        bridge.assert_target(tid)
        if authorize: authorize()
        previous = bridge.journal.get(request_id)
        if previous:
            if previous['fingerprint'] != fingerprint: raise BridgeError('requestId 已用于不同内容')
            return previous
        job = {'id': request_id, 'kind': 'fork', 'threadId': tid, 'sourceThreadId': tid,
               'lastTurnId': last, 'fingerprint': fingerprint, 'state': 'preparing',
               'created': time.time(), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=dispatch, args=(bridge, ipc, generation, job, authorize),
                     daemon=True, name='native-fork').start()
    return bridge.journal.get(request_id)


def dispatch(bridge, ipc, generation, job, authorize):
    tid = job['sourceThreadId']; sent = False; creator = None
    def authorized():
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            bridge.assert_target(tid)
            if authorize: authorize()
    try:
        if getattr(ipc, 'protocol', None) == 'codex-app-server':
            session = nullcontext((ipc, lambda write: write()))
        elif hasattr(bridge, 'native_session'):
            session = bridge.native_session(tid, authorized)
        else:
            raise IPCError('当前桌面会话未提供可验证的原生分叉入口')
        with session as target:
            if target is None: raise IPCError('当前桌面会话不支持分叉；请先加载到 CarryOn')
            runtime, owner_guard = target
            _, state = runtime.snapshot(tid)
            if state.get('threadMetadata', {}).get('historyMode') != 'paginated':
                raise IPCError('此会话不支持原生分页分叉')
            if not state['turns']: raise IPCError('会话尚无可分叉的轮次')
            selected = job.get('lastTurnId') or state['turns'][-1]['turnId']
            identity = (runtime.process, runtime.session_id)
            def valid_source():
                current = runtime.current(tid)
                if (not current or current.get('_metadataOnly') or not runtime.connected
                        or (runtime.process, runtime.session_id) != identity):
                    raise IPCError('来源会话连接已改变')
                turn = next((t for t in current['turns'] if t['turnId'] == selected), None)
                if turn is None or turn['status'] not in ('completed', 'failed', 'interrupted'):
                    raise IPCError('请选择已结束的来源轮次')
                if job.get('lastTurnId') is None and current['turns'][-1]['turnId'] != selected:
                    raise IPCError('来源会话已新增轮次，请刷新后分叉')
                return current
            with runtime._queue_lock(tid):
                authorized(); valid_source()
                # A separate writer owns only the child. Forks are durable without
                # a first prompt, so the normal Owner loader can reopen it later.
                creator = AppServer(runtime.home, runtime_directory=runtime.runtime_directory / 'forks' / job['id'])
                creator.connect(); creator.require_account()
                def guarded(write):
                    nonlocal sent
                    with bridge.lock:
                        authorized()
                        def checked():
                            nonlocal sent
                            with runtime.lock:
                                valid_source()
                                bridge.journal.update(job['id'], state='dispatching', forkThroughTurnId=selected)
                                sent = True
                                write()
                        owner_guard(checked)
                result = creator.rpc('thread/fork', {'threadId': tid, 'lastTurnId': selected,
                    'excludeTurns': True, 'deferGoalContinuation': True}, guarded)
                child = result['thread']; child_id = valid_id(child['id'])
                bridge.journal.update(job['id'], createdThreadId=child_id)
                if (child_id == tid or child.get('forkedFromId') != tid
                        or child.get('historyMode') != 'paginated' or not Path(child.get('cwd', '')).is_absolute()
                        or not Path(state.get('cwd', '')).is_absolute()
                        or Path(child['cwd']).resolve() != Path(state['cwd']).resolve()
                        or child.get('status', {}).get('type') != 'idle'):
                    raise IPCError('分叉已创建，但原生返回的来源或状态需要核对', uncertain=True)
                # Do not publish a usable child while its temporary writer still
                # holds the native lock: the next request may immediately load it.
                creator.close()
                creator = None
                bridge.journal.update(job['id'], state='completed', threadId=child_id,
                    evidence='native-thread-fork-response')
    except Exception as exc:
        uncertain = sent and (not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
    finally:
        if creator is not None: creator.close()
        if bridge.journal.get(job['id'])['state'] == 'completed' and hasattr(bridge, 'workspace'):
            try: bridge.workspace.catalog_refresh()
            except (OSError, ValueError, IPCError, BridgeError) as exc:
                # Creation is already confirmed. A catalog read cannot undo it.
                bridge.journal.update(job['id'], catalogRefreshError=str(exc))
        bridge.notify()
