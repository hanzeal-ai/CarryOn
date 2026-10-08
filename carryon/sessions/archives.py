"""Native archive/restore receipts. No automatic resume, replay, or filesystem cleanup."""
from contextlib import nullcontext
import threading
import time

from carryon.app_server.app_server import AppServer
from carryon.app_server.goals import read as read_goal, value as goal_value
from carryon.app_server.queue import messages as queue_messages
from carryon.app_server.realtime_voice import held as voice_held
from carryon.contracts import digest, validate_request_id
from carryon.desktop_ipc.ipc import IPCError
from carryon.errors import BridgeError
from carryon.sessions.catalog import valid_id
from carryon.sessions.native_metadata import record, supported

KINDS = {'archive', 'unarchive'}



def submit(bridge, tid, action, data, source=None, authorize=None):
    valid_id(tid)
    if action not in KINDS or not isinstance(data, dict) or set(data) != {'requestId'}:
        raise ValueError('归档操作只接受 requestId')
    request_id = data['requestId']; validate_request_id(request_id)
    ipc, generation = bridge.require()
    fingerprint = digest([action, tid])
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        if not supported(bridge): raise IPCError('桌面 follower 未提供公开归档入口')
        previous = bridge.journal.get(request_id)
        if previous:
            if previous['fingerprint'] != fingerprint: raise BridgeError('requestId 已用于不同内容')
            return previous
        row = record(bridge, tid)
        if bool(row['archived']) != (action == 'unarchive'):
            raise IPCError('会话归档状态已改变，请刷新')
        if any((job['threadId'] == tid or job['kind'] == 'section-order' and job.get('body', {}).get('beforeThreadId') == tid) and job['state'] in ('preparing', 'dispatching', 'uncertain')
               and job['kind'] in KINDS | {'rename', 'section-move', 'section-order', 'terminal-terminate', 'terminal-clean', 'skill-config', 'plugin-install', 'plugin-uninstall'} for job in bridge.journal.list()):
            raise IPCError('归档结果待核对，请先核对原请求')
        job = {'id': request_id, 'kind': action, 'threadId': tid, 'fingerprint': fingerprint,
               'state': 'preparing', 'created': time.time(), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=dispatch, args=(bridge, ipc, generation, job, authorize),
                     daemon=True, name='native-' + action).start()
    return bridge.journal.get(request_id)


def safe_idle(runtime, tid, identity, state=None, queue=None, goal=None):
    state = state if state is not None else runtime.current(tid)
    if (not runtime.connected or (runtime.process, runtime.session_id) != identity
            or not state or state.get('_metadataOnly') or state['threadRuntimeStatus']['type'] != 'idle'
            or state.get('requests') or (bool(queue) if queue is not None else runtime.queue_busy(tid))
            or any(turn['status'] == 'inProgress' for turn in state['turns'])
            or state.get('_goalUnknown') or (goal if goal is not None else state.get('threadGoal') or {}).get('status') == 'active'
            or voice_held(state) or state.get('threadMetadata', {}).get('ephemeral')):
        raise IPCError('归档需要空闲、空队列、无审批、无运行目标或语音的持久会话')


def finish(bridge, job, ipc, generation):
    bridge.check_generation(ipc, generation)
    tid = job['threadId']; archived = job['kind'] == 'archive'
    if bool(record(bridge, tid)['archived']) != archived:
        raise IPCError('原生归档状态尚未确认', uncertain=True)
    if archived and hasattr(bridge, 'owner_service'):
        from carryon.owner.archive_control import detach
        detach(bridge, tid, job.get('archiveOwnerSessionId'))
    if archived and getattr(ipc, 'protocol', None) == 'codex-app-server':
        with ipc.lock:
            ipc.snapshots.pop(tid, None); ipc.following.pop(tid, None)
    result = bridge.journal.update(job['id'], state='completed', error=None,
        evidence='native-archive-catalog-confirmed', result={'threadId': tid, 'archived': archived})
    if hasattr(bridge, 'workspace'):
        try: bridge.workspace.catalog_refresh()
        except (OSError, ValueError, IPCError, BridgeError) as error:
            result = bridge.journal.update(job['id'], catalogRefreshError=str(error))
    return result


def dispatch(bridge, ipc, generation, job, authorize):
    tid = job['threadId']; action = job['kind']; sent = False; replied = False; reader = None
    def authorized():
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
    try:
        if action == 'archive':
            if getattr(ipc, 'protocol', None) == 'codex-app-server':
                session = nullcontext((ipc, lambda write: write(), lambda: ipc.current(tid), False, None))
            else:
                from carryon.owner.native_control import session as owned_session
                session = owned_session(bridge, tid)
            with session as (runtime, owner_guard, state_provider, suspended, owner_session), runtime._queue_lock(tid):
                authorized(); identity = (runtime.process, runtime.session_id)
                if suspended:
                    queue = queue_messages(runtime, tid)
                    goal = goal_value(runtime.rpc('thread/goal/get', {'threadId': tid}), tid)
                else:
                    queue = runtime.queue_snapshot(tid, refresh=True)
                    goal = read_goal(runtime, tid)['goal']
                from carryon.app_server.background_terminals import empty, verify as verify_terminals
                terminal_proof = None if suspended else empty(runtime, tid)
                safe_idle(runtime, tid, identity, state_provider(), queue, goal)
                def guarded(write):
                    nonlocal sent
                    with bridge.lock:
                        authorized()
                        def checked():
                            nonlocal sent
                            with runtime.lock:
                                safe_idle(runtime, tid, identity, state_provider(), queue if suspended else None, goal if suspended else None)
                                if terminal_proof is not None: verify_terminals(runtime, tid, terminal_proof)
                                if record(bridge, tid)['archived']: raise IPCError('会话已归档')
                                job['archiveOwnerSessionId'] = owner_session
                                bridge.journal.update(job['id'], state='dispatching', archiveOwnerSessionId=owner_session); sent = True; write()
                        owner_guard(checked)
                runtime.rpc('thread/archive', {'threadId': tid}, guarded); replied = True
                with bridge.lock:
                    authorized(); finish(bridge, job, ipc, generation)
        else:
            # Unarchive reads persisted state and never resumes a paused goal.
            service = bridge.owners() if hasattr(bridge, 'owners') else None
            transaction = service._thread_lock(tid) if service else nullcontext()
            with transaction:
                if service:
                    service._connect_bus()
                    with service.lock:
                        if tid in service.entries or tid in service.loading: raise IPCError('会话仍有 CarryOn Owner，请先核对归档')
                    reader = service.prewarm.take()
                else:
                    reader = AppServer(ipc.home, runtime_directory=ipc.runtime_directory / 'archives' / job['id'])
                    reader.connect()
                reader.require_account()
                def guarded(write):
                    nonlocal sent
                    with bridge.lock:
                        authorized()
                        if not record(bridge, tid)['archived']: raise IPCError('会话已恢复')
                        if service:
                            try: service.bus.owner(tid, timeout_ms=3000)
                            except IPCError as error:
                                if str(error) != 'no-client-found': raise
                            else: raise IPCError('会话已被其他 Owner 加载')
                        bridge.journal.update(job['id'], state='dispatching'); sent = True; write()
                response = reader.rpc('thread/unarchive', {'threadId': tid}, guarded); replied = True
                thread = response.get('thread', {})
                if thread.get('id') != tid or thread.get('status', {}).get('type') != 'notLoaded':
                    raise IPCError('恢复回执身份或状态需要核对', uncertain=True)
                reader.close(); reader = None
                with bridge.lock:
                    authorized(); finish(bridge, job, ipc, generation)
    except Exception as error:
        uncertain = sent and (replied or not isinstance(error, IPCError) or error.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(error))
    finally:
        if reader: reader.close()
        bridge.notify()


def recover(bridge, job):
    # Explicit status query only; the native writer is never reopened or re-dispatched.
    ipc, generation = bridge.require()
    service = getattr(bridge, 'owner_service', None)
    transaction = service._thread_lock(job['threadId']) if service else nullcontext()
    with transaction, bridge.lock:
        bridge.check_generation(ipc, generation)
        if getattr(bridge, 'owner_service', None) is not service:
            raise IPCError('归档查询期间 Owner 服务已改变')
        if bool(record(bridge, job['threadId'])['archived']) != (job['kind'] == 'archive'): return job
        return finish(bridge, job, ipc, generation)
