"""Stop only terminals verified in the actual owning native process."""
from contextlib import contextmanager, nullcontext
import threading
import time
from carryon.app_server import background_terminals as native
from carryon.contracts import digest, validate_request_id
from carryon.desktop_ipc.ipc import IPCError
from carryon.errors import BridgeError
from carryon.sessions.catalog import valid_id
from carryon.sessions.native_metadata import record


@contextmanager
def live(bridge, tid, authorize=None, expected_bridge=None):
    valid_id(tid); bridge.assert_target(tid)
    ipc, generation = bridge.require()
    if expected_bridge is not None: bridge.check_generation(*expected_bridge)
    if authorize: authorize()
    if getattr(ipc, 'protocol', None) == 'codex-app-server':
        session = nullcontext((ipc, lambda write: write(), None, False, None))
    elif getattr(bridge, 'owner_service', None) is not None:
        from carryon.owner.native_control import session as owner_session
        session = owner_session(bridge, tid, loaded_only=True)
    else: raise IPCError('当前会话没有 CarryOn 原生终端进程')
    with session as (runtime, owner_guard, _state, _suspended, _owner_id), runtime._queue_lock(tid):
        expected = native.identity(runtime, tid)
        def guard(write):
            with bridge.lock:
                bridge.check_generation(ipc, generation)
                if authorize: authorize()
                if record(bridge, tid)['archived']: raise IPCError('会话已归档')
                def checked():
                    native.verify(runtime, tid, expected); write()
                owner_guard(checked)
        guard(lambda: None)
        yield runtime, guard, expected


def read(bridge, tid, query, authorize=None):
    limit = int(query.get('limit', ['50'])[0]); cursor = query.get('cursor', [None])[0]
    with live(bridge, tid, authorize) as (runtime, guard, _identity):
        result, _ = native.page(runtime, tid, limit, cursor)
        guard(lambda: None)
        return {'threadId': tid, 'terminals': [{'id': row['processId'], **row} for row in result['terminals']], 'nextCursor': result['nextCursor']}


def rows(runtime, tid):
    result, _ = native.page(runtime, tid, limit=100)
    records, seen, cursor = result['terminals'], set(), result['nextCursor']
    for _ in range(99):
        if cursor is None: return records
        if cursor in seen: raise IPCError('终端分页游标重复')
        seen.add(cursor); result, _ = native.page(runtime, tid, limit=100, cursor=cursor)
        known = {row['processId'] for row in records}
        if any(row['processId'] in known for row in result['terminals']): raise IPCError('后台终端身份跨页重复')
        records += result['terminals']; cursor = result['nextCursor']
    if cursor is not None: raise IPCError('后台终端列表过长')
    return records


def submit(bridge, tid, data, source=None, authorize=None):
    valid_id(tid)
    action = data.get('action') if isinstance(data, dict) else None
    if action not in ('terminate', 'clean') or set(data) != {'requestId', 'action'} | ({'processId'} if action == 'terminate' else set()): raise ValueError('后台终端操作字段无效')
    if action == 'terminate' and (not isinstance(data['processId'], str) or not 0 < len(data['processId']) <= 256): raise ValueError('原生终端身份无效')
    key = data['requestId']; validate_request_id(key)
    body = {k: v for k, v in data.items() if k != 'requestId'}
    ipc, generation = bridge.require()
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        fingerprint = digest(['terminal', tid, body]); prior = bridge.journal.get(key)
        if prior:
            if prior['fingerprint'] != fingerprint: raise BridgeError('requestId已用于不同内容')
            return prior
        bridge.assert_target(tid)
        if getattr(ipc, 'protocol', None) != 'codex-app-server' and getattr(bridge, 'owner_service', None) is None: raise IPCError('当前会话没有 CarryOn 原生终端进程')
        for prior in bridge.journal.list():
            involved = prior['threadId'] == tid or prior['kind'] == 'section-order' and prior.get('body', {}).get('beforeThreadId') == tid
            if involved and prior['kind'] in ('terminal-terminate', 'terminal-clean', 'archive', 'unarchive', 'section-order') and prior['state'] in ('preparing', 'dispatching', 'uncertain'): raise IPCError('会话操作待核对，请先核对原请求')
        job = {'id': key, 'kind': 'terminal-' + action, 'threadId': tid, 'body': body, 'fingerprint': fingerprint, 'state': 'preparing', 'created': time.time(), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=run, args=(bridge, ipc, generation, job, authorize), daemon=True, name='native-terminal-' + action).start()
    return bridge.journal.get(key)


def confirmation(runtime, job):
    records = rows(runtime, job['threadId'])
    action = job['body']['action']
    if records if action == 'clean' else any(row['processId'] == job['body']['processId'] for row in records): raise IPCError('原生终端停止尚未确认', uncertain=True)
    return {'threadId': job['threadId'], **({'cleaned': True} if action == 'clean' else {'processId': job['body']['processId'], 'terminated': True})}


def run(bridge, ipc, generation, job, authorize):
    sent = replied = False
    try:
        with live(bridge, job['threadId'], authorize, (ipc, generation)) as (runtime, guard, expected):
            current = rows(runtime, job['threadId'])
            action = job['body']['action']
            if action == 'terminate' and not any(row['processId'] == job['body']['processId'] for row in current): raise IPCError('原生终端已结束或不属于当前会话')
            with bridge.lock:
                guard(lambda: None)
                bridge.journal.update(job['id'], nativeSessionId=expected[1], nativeProcessPid=expected[0].pid)
            def guarded(write):
                def checked():
                    nonlocal sent
                    bridge.journal.update(job['id'], state='dispatching'); sent = True; write()
                guard(checked)
            runtime.rpc('thread/backgroundTerminals/' + action, {'threadId': job['threadId'], **({'processId': job['body']['processId']} if action == 'terminate' else {})}, guarded); replied = True
            result = confirmation(runtime, job)
            with bridge.lock:
                guard(lambda: None)
                bridge.journal.update(job['id'], state='completed', result=result, error=None, evidence='native-terminal-absent')
    except Exception as error:
        uncertain = sent and (replied or not isinstance(error, IPCError) or error.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(error))
    finally: bridge.notify()


def recover(bridge, job):
    try:
        with live(bridge, job['threadId']) as (runtime, guard, expected):
            if expected[1] != job.get('nativeSessionId') or expected[0].pid != job.get('nativeProcessPid'): return job
            result = confirmation(runtime, job)
            with bridge.lock:
                guard(lambda: None)
                return bridge.journal.update(job['id'], expected=job, state='completed', result=result, error=None, evidence='native-terminal-absent')
    except (ValueError, IPCError, BridgeError): return job
