"""Persistent native thread names; no task resume or uncertain-write replay."""
from contextlib import nullcontext
import threading
import time
from carryon.contracts import digest, validate_request_id
from carryon.errors import IPCError
from carryon.errors import BridgeError
from carryon.sessions.native_metadata import record, supported


def submit(bridge, tid, data, source=None, authorize=None):
    from carryon.sessions.catalog import valid_id
    valid_id(tid)
    if not isinstance(data, dict) or set(data) != {'requestId', 'name'}:
        raise ValueError('重命名只接受 requestId 与 name')
    name = data['name']
    if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(c) < 32 for c in name):
        raise ValueError('名称须为非空单行文字，最多200字符')
    name = name.strip(); key = data['requestId']; validate_request_id(key)
    ipc, generation = bridge.require()
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        if not supported(bridge): raise IPCError('桌面 follower 未提供公开重命名入口')
        prior = bridge.journal.get(key); fingerprint = digest(['rename', tid, name])
        if prior:
            if prior['fingerprint'] != fingerprint: raise BridgeError('requestId 已用于不同内容')
            return prior
        if record(bridge, tid)['archived']: raise IPCError('请先恢复已归档会话')
        if any(j['threadId'] == tid and j['kind'] in ('rename', 'archive', 'unarchive') and
               j['state'] in ('preparing', 'dispatching', 'uncertain') for j in bridge.journal.list()):
            raise IPCError('会话名称或归档操作待核对，请先核对原请求')
        job = {'id': key, 'kind': 'rename', 'threadId': tid, 'name': name, 'fingerprint': fingerprint,
               'state': 'preparing', 'created': time.time(), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=dispatch, args=(bridge, ipc, generation, job, authorize),
                     daemon=True, name='native-rename').start()
    return bridge.journal.get(key)


def validate_confirmation(bridge, ipc, generation, job, thread):
    bridge.check_generation(ipc, generation)
    if thread.get('id') != job['threadId'] or thread.get('name') != job['name']:
        raise IPCError('原生名称尚未确认，请核对原请求', uncertain=True)


def project_suspended_name(service, job, thread):
    from carryon.sessions.history_cache import NativeSnapshot
    entry = service.entries.get(job['threadId'])
    if not entry or not entry.get('suspended'): return
    entry['snapshot'] = NativeSnapshot({**entry['snapshot'], 'title': thread['name'],
        'threadMetadata': {**entry['snapshot'].get('threadMetadata', {}), 'name': thread['name']}})
    service.publish(job['threadId'], force=True)


def confirm(bridge, ipc, generation, job, thread):
    validate_confirmation(bridge, ipc, generation, job, thread)
    return bridge.journal.update(job['id'], state='completed', error=None,
        evidence='native-thread-name-confirmed', result={'threadId': job['threadId'], 'name': job['name']})


def dispatch(bridge, ipc, generation, job, authorize):
    tid = job['threadId']; sent = False; replied = False
    try:
        if getattr(ipc, 'protocol', None) == 'codex-app-server':
            context = nullcontext((ipc, lambda write: write(), lambda: ipc.current(tid), False, None))
        else:
            from carryon.owner.native_control import session
            context = session(bridge, tid)
        with context as (runtime, owner_guard, state, suspended, _):
            with runtime._queue_lock(tid):
                identity = runtime.connection_identity
                def stable():
                    if not runtime.connected or runtime.connection_identity != identity:
                        raise IPCError('原生连接身份已改变')
                def guarded(write):
                    nonlocal sent
                    with bridge.lock:
                        bridge.check_generation(ipc, generation)
                        if authorize: authorize()
                        if record(bridge, tid)['archived']: raise IPCError('会话已归档')
                        def checked():
                            nonlocal sent
                            stable()
                            snapshot = state()
                            if not snapshot or snapshot.get('threadMetadata', {}).get('ephemeral'):
                                raise IPCError('会话尚未就绪或不是持久会话')
                            bridge.journal.update(job['id'], state='dispatching'); sent = True; write()
                        owner_guard(checked)
                runtime.rpc('thread/name/set', {'threadId': tid, 'name': job['name']}, guarded); replied = True
                stable()
                thread = runtime.rpc('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
                with bridge.lock:
                    if authorize: authorize()
                    def finish():
                        stable()
                        validate_confirmation(bridge, ipc, generation, job, thread)
                        if suspended:
                            project_suspended_name(bridge.owner_service, job, thread)
                        confirm(bridge, ipc, generation, job, thread)
                    owner_guard(finish)
    except Exception as error:
        uncertain = sent and (replied or not isinstance(error, IPCError) or error.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(error))
    finally: bridge.notify()


def recover(bridge, job):
    # Persisted metadata is sufficient evidence; never load a runtime or repeat the write.
    ipc, generation = bridge.require()
    service = getattr(bridge, 'owner_service', None)
    transaction = service._thread_lock(job['threadId']) if service else nullcontext()
    with transaction, bridge.lock:
        bridge.check_generation(ipc, generation)
        if getattr(bridge, 'owner_service', None) is not service: raise IPCError('名称核对期间 Owner 服务已改变')
        row = record(bridge, job['threadId'])
        if row.get('name') != job['name']: return job
        thread = {'id': row['id'], 'name': row['name']}
        validate_confirmation(bridge, ipc, generation, job, thread)
        if service:
            with service.lock: project_suspended_name(service, job, thread)
        return confirm(bridge, ipc, generation, job, thread)
