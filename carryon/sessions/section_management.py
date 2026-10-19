"""Native section lifecycle receipts; ambiguous creation is never guessed or replayed."""
import threading
import time
from carryon.codex_protocol.read_control import reader
from carryon.contracts import digest, validate_request_id
from carryon.errors import IPCError
from carryon.errors import BridgeError
from carryon.sessions.catalog import valid_id
from carryon.sessions.native_metadata import record, supported
from carryon.sessions.sections import PINNED_SECTION


def inventory(runtime, verify):
    cursor, seen, rows = None, set(), []
    for _ in range(100):
        result = runtime.rpc('threadSection/list', {'limit': 100, **({'cursor': cursor} if cursor else {})})
        verify()
        if not isinstance(result, dict) or not isinstance(result.get('data'), list): raise IPCError('原生分组回执无效')
        for row in result['data']:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str): raise IPCError('原生分组格式无效')
            valid_id(row.get('id')); rows.append(row)
        cursor = result.get('nextCursor')
        if cursor is None: return rows
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in seen: raise IPCError('分组分页游标无效')
        seen.add(cursor)
    raise IPCError('分组列表过长，无法核对目标')


def submit(bridge, section_id, data, source=None, authorize=None):
    if section_id is not None: valid_id(section_id)
    if not isinstance(data, dict): raise ValueError('分组管理请求无效')
    action = 'create' if section_id is None else data.get('action')
    if action not in ('create', 'update', 'delete', 'order'): raise ValueError('分组管理操作无效')
    expected = {'requestId', 'name'} if action == 'create' else {'requestId', 'action'} | ({'name'} if action == 'update' else set())
    if action == 'order':
        expected = {'requestId', 'action', 'threadId', 'beforeThreadId'}
        valid_id(data.get('threadId'))
        if data.get('beforeThreadId') is not None: valid_id(data['beforeThreadId'])
        if data.get('beforeThreadId') == data['threadId']: raise ValueError('会话不能排在自身之前')
    if set(data) != expected: raise ValueError('分组管理字段无效')
    if action in ('create', 'update') and (not isinstance(data['name'], str) or not data['name'].strip() or len(data['name']) > 200 or '\x00' in data['name']): raise ValueError('分组名称须为1–200字符')
    if section_id == PINNED_SECTION and action != 'order': raise ValueError('内置置顶分组不能修改或删除')
    key = data['requestId']; validate_request_id(key)
    body = {k: v for k, v in data.items() if k != 'requestId'}
    ipc, generation = bridge.require()
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        if not supported(bridge): raise IPCError('当前连接未提供公开分组管理')
        fingerprint = digest(['section-' + action, section_id, body])
        prior = bridge.journal.get(key)
        if prior:
            if prior['fingerprint'] != fingerprint: raise BridgeError('requestId已用于不同内容')
            return prior
        for prior in bridge.journal.list():
            if prior['state'] not in ('preparing', 'dispatching', 'uncertain'): continue
            if prior['kind'].startswith('section-'):
                raise IPCError('分组操作待核对，请先核对原请求')
        if action == 'order':
            if record(bridge, data['threadId'])['archived']: raise IPCError('请先恢复已归档会话')
            if data['beforeThreadId'] is not None and record(bridge, data['beforeThreadId'])['archived']: raise IPCError('排序参照会话已归档')
            if any(j['threadId'] in {data['threadId'], data['beforeThreadId']} and j['kind'] in ('archive', 'unarchive', 'terminal-terminate', 'terminal-clean') and j['state'] in ('preparing', 'dispatching', 'uncertain') for j in bridge.journal.list()): raise IPCError('归档操作待核对，请先核对原请求')
        job = {'id': key, 'kind': 'section-' + action, 'threadId': data['threadId'] if action == 'order' else section_id or 'sections', 'sectionId': section_id, 'body': body, 'fingerprint': fingerprint, 'state': 'preparing', 'created': time.time(), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=run, args=(bridge, ipc, generation, job, authorize), daemon=True, name='native-section-' + action).start()
    return bridge.journal.get(key)


def ordered_threads(runtime, verify, section_id):
    cursor, seen, rows = None, set(), []
    for _ in range(100):
        result = runtime.rpc('thread/list', {'sectionId': section_id, 'sortKey': 'section_position', 'archived': False, 'limit': 100, **({'cursor': cursor} if cursor else {})})
        verify()
        if not isinstance(result, dict) or not isinstance(result.get('data'), list): raise IPCError('原生分组顺序回执无效')
        for row in result['data']:
            if not isinstance(row, dict) or (row.get('section') or {}).get('id') != section_id: raise IPCError('原生排序归属不匹配')
            tid = valid_id(row.get('id'))
            if tid in rows: raise IPCError('原生排序会话重复')
            rows.append(tid)
        cursor = result.get('nextCursor')
        if cursor is None: return rows
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in seen: raise IPCError('分组分页游标无效')
        seen.add(cursor)
    raise IPCError('分组列表过长，无法核对顺序')


def confirmed(runtime, verify, job):
    if job['kind'] == 'section-order':
        rows = ordered_threads(runtime, verify, job['sectionId'])
        tid, before = job['threadId'], job['body']['beforeThreadId']
        if tid not in rows or (rows[-1] != tid if before is None else before not in rows or rows.index(tid) + 1 != rows.index(before)):
            raise IPCError('原生分组顺序尚未确认', uncertain=True)
        return {'threadId': tid, 'sectionId': job['sectionId'], 'beforeThreadId': before}
    rows = inventory(runtime, verify)
    section = next((row for row in rows if row['id'] == job['sectionId']), None)
    if job['kind'] == 'section-delete':
        if section is not None: raise IPCError('原生分组删除尚未确认', uncertain=True)
        return {'sectionId': job['sectionId'], 'deleted': True}
    if section is None or section['name'] != job['body']['name']: raise IPCError('原生分组修改尚未确认', uncertain=True)
    return {'section': section}


def run(bridge, ipc, generation, job, authorize):
    sent = replied = False
    try:
        with reader(bridge) as (runtime, verify):
            action = job['kind'].removeprefix('section-')
            if action != 'create' and not any(row['id'] == job['sectionId'] for row in inventory(runtime, verify)): raise IPCError('分组已不存在')
            if action == 'order':
                rows = ordered_threads(runtime, verify, job['sectionId'])
                if job['threadId'] not in rows or job['body']['beforeThreadId'] is not None and job['body']['beforeThreadId'] not in rows: raise IPCError('排序会话不属于目标分组')
            def guarded(write):
                nonlocal sent
                with bridge.lock:
                    verify(); bridge.check_generation(ipc, generation)
                    if authorize: authorize()
                    if action == 'order':
                        for tid in {job['threadId'], job['body']['beforeThreadId']} - {None}:
                            if record(bridge, tid)['archived']: raise IPCError('排序会话已归档')
                    bridge.journal.update(job['id'], state='dispatching'); sent = True; write()
            params = ({'name': job['body']['name']} if action == 'create' else {'sectionId': job['sectionId'], **({'name': job['body']['name']} if action == 'update' else {})})
            if action == 'order': params = {'sectionId': job['sectionId'], 'threadId': job['threadId'], 'beforeThreadId': job['body']['beforeThreadId']}
            response = runtime.rpc('thread/section/move' if action == 'order' else 'threadSection/' + action, params, guarded); replied = True
            verify()
            if action == 'create':
                section = response.get('section') if isinstance(response, dict) else None
                if not isinstance(section, dict) or section.get('name') != job['body']['name']: raise IPCError('原生分组创建回执不匹配', uncertain=True)
                valid_id(section.get('id'))
                result = {'section': section}
            else: result = confirmed(runtime, verify, job)
            with bridge.lock:
                verify(); bridge.check_generation(ipc, generation)
                if authorize: authorize()
                bridge.journal.update(job['id'], state='completed', result=result, error=None, evidence='native-section-' + action)
    except Exception as error:
        uncertain = sent and (replied or not isinstance(error, IPCError) or error.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(error))
    finally: bridge.notify()


def recover(bridge, job):
    # Public create has no client identity: a matching name cannot prove this request created it.
    if job['kind'] == 'section-create': return job
    with reader(bridge) as (runtime, verify):
        try: result = confirmed(runtime, verify, job)
        except IPCError: return job
        with bridge.lock:
            verify()
            return bridge.journal.update(job['id'], expected=job, state='completed', result=result, error=None, evidence='native-section-confirmed')
