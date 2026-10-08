"""Native persisted sidebar groups and thread membership; never resume a task."""
import threading
import time
from carryon.app_server.read_control import reader
from carryon.contracts import digest, validate_request_id
from carryon.desktop_ipc.ipc import IPCError
from carryon.errors import BridgeError
from carryon.sessions.catalog import valid_id
from carryon.sessions.native_metadata import record, supported

# Native reserved identity, confirmed by the Desktop client and public inventory.
PINNED_SECTION = '01984de2-8f74-7c91-a3b2-5c5e937cf318'


def membership(bridge, tid, authorize=None):
    valid_id(tid)
    if record(bridge, tid)['archived']: raise IPCError('请先恢复已归档会话')
    if authorize: authorize()
    with reader(bridge) as (runtime, verify):
        thread = runtime.rpc('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
        if thread.get('id') != tid: raise IPCError('原生分组会话身份不匹配')
        verify()
        if record(bridge, tid)['archived']: raise IPCError('读取期间会话已归档')
        if authorize: authorize()
        verify()
        section = thread.get('section')
        if section is not None:
            valid_id(section['id'])
            if not isinstance(section.get('name'), str): raise IPCError('原生分组格式无效')
        return {'threadId': tid, 'sectionId': section['id'] if section else None}


def page(bridge, query, section_id=None, authorize=None):
    limit = int(query.get('limit', ['50'])[0])
    cursor = query.get('cursor', [None])[0]
    if not 1 <= limit <= 100: raise ValueError('分组页大小须为1–100')
    if cursor is not None and (not cursor or len(cursor) > 4096 or '\x00' in cursor): raise ValueError('分组游标无效')
    if section_id is not None: valid_id(section_id)
    if authorize: authorize()
    with reader(bridge) as (runtime, verify):
        params = {'limit': limit, **({'cursor': cursor} if cursor else {})}
        if section_id is not None: params.update(sectionId=section_id, sortKey='section_position', archived=False)
        result = runtime.rpc('thread/list' if section_id else 'threadSection/list', params)
        verify()
        if not isinstance(result, dict) or not isinstance(result.get('data'), list): raise IPCError('原生分组回执无效')
        cursor = result.get('nextCursor')
        if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096): raise IPCError('原生分组游标无效')
        rows = []
        for item in result['data']:
            if not isinstance(item, dict): raise IPCError('原生分组记录无效')
            tid = valid_id(item.get('id'))
            if section_id is None:
                rows.append({'id': tid, 'title': item['name'], 'appearance': item.get('appearance'), 'pinned': tid == PINNED_SECTION})
            else:
                try: native = record(bridge, tid)
                except (ValueError, IPCError): continue
                if native.get('archived'): continue
                if item.get('section', {}).get('id') != section_id: raise IPCError('原生分组会话归属不匹配')
                rows.append({'id': tid, 'title': native.get('name') or native.get('title') or '未命名会话', 'cwd': native['cwd'], 'sectionId': section_id})
        verify()
        if authorize: authorize()
        return {('threads' if section_id else 'sections'): rows, 'nextCursor': cursor}


def submit(bridge, tid, data, source=None, authorize=None):
    valid_id(tid)
    if not isinstance(data, dict) or set(data) != {'requestId', 'sectionId'}: raise ValueError('分组移动只接受requestId与sectionId')
    destination = data['sectionId']
    if destination is not None: valid_id(destination)
    key = data['requestId']; validate_request_id(key)
    ipc, generation = bridge.require()
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        if not supported(bridge): raise IPCError('当前连接未提供公开分组管理')
        fingerprint = digest(['section-move', tid, destination])
        prior = bridge.journal.get(key)
        if prior:
            if prior['fingerprint'] != fingerprint: raise BridgeError('requestId已用于不同内容')
            return prior
        if record(bridge, tid)['archived']: raise IPCError('请先恢复已归档会话')
        if any(j['kind'] in ('section-create', 'section-update', 'section-delete', 'section-order') and j['state'] in ('preparing', 'dispatching', 'uncertain') for j in bridge.journal.list()):
            raise IPCError('分组管理操作待核对，请先核对原请求')
        if any(j['threadId'] == tid and j['kind'] in ('section-move', 'archive', 'unarchive') and j['state'] in ('preparing', 'dispatching', 'uncertain') for j in bridge.journal.list()):
            raise IPCError('分组或归档操作待核对，请先核对原请求')
        job = {'id': key, 'kind': 'section-move', 'threadId': tid, 'sectionId': destination, 'fingerprint': fingerprint, 'state': 'preparing', 'created': time.time(), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=move, args=(bridge, ipc, generation, job, authorize), daemon=True, name='native-section-move').start()
    return bridge.journal.get(key)


def confirmation(runtime, job):
    thread = runtime.rpc('thread/read', {'threadId': job['threadId'], 'includeTurns': False})['thread']
    if thread.get('id') != job['threadId'] or (thread.get('section') or {}).get('id') != job['sectionId']:
        raise IPCError('原生分组尚未确认，请核对原请求', uncertain=True)
    return {'threadId': job['threadId'], 'sectionId': job['sectionId']}


def move(bridge, ipc, generation, job, authorize):
    sent = replied = False
    try:
        with reader(bridge) as (runtime, verify):
            if job['sectionId'] is not None:
                from carryon.sessions.section_management import inventory
                if not any(row['id'] == job['sectionId'] for row in inventory(runtime, verify)): raise IPCError('目标分组已不存在')
            def guarded(write):
                nonlocal sent
                with bridge.lock:
                    verify(); bridge.check_generation(ipc, generation)
                    if authorize: authorize()
                    if record(bridge, job['threadId'])['archived']: raise IPCError('会话已归档')
                    bridge.journal.update(job['id'], state='dispatching'); sent = True; write()
            runtime.rpc('thread/section/move', {'threadId': job['threadId'], 'sectionId': job['sectionId']}, guarded); replied = True
            verify(); result = confirmation(runtime, job)
            with bridge.lock:
                verify(); bridge.check_generation(ipc, generation)
                if authorize: authorize()
                bridge.journal.update(job['id'], state='completed', error=None, evidence='native-section-confirmed', result=result)
    except Exception as error:
        uncertain = sent and (replied or not isinstance(error, IPCError) or error.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(error))
    finally: bridge.notify()


def recover(bridge, job):
    with reader(bridge) as (runtime, verify):
        try: result = confirmation(runtime, job)
        except IPCError: return job
        with bridge.lock:
            verify()
            return bridge.journal.update(job['id'], expected=job, state='completed', error=None, evidence='native-section-confirmed', result=result)
