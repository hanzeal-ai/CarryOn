"""Read native message search without loading, resuming or executing a task."""
from carryon.app_server.read_control import reader
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.native_metadata import record
from carryon.sessions.catalog import valid_id


def parameters(query):
    term = query.get('search', [''])[0].strip()
    if not term or len(term) > 200: raise ValueError('搜索内容须为 1–200 个字符')
    limit = int(query.get('limit', ['30'])[0])
    if not 1 <= limit <= 50: raise ValueError('搜索页大小须为 1–50')
    cursor = query.get('cursor', [None])[0]
    if cursor is not None and (not cursor or len(cursor) > 4096 or '\x00' in cursor): raise ValueError('搜索游标无效')
    return {'searchTerm': term, 'limit': limit, **({'cursor': cursor} if cursor is not None else {})}




def page(bridge, query, thread_id=None, authorize=None):
    params = parameters(query)
    if thread_id is not None:
        valid_id(thread_id)
        if record(bridge, thread_id).get('archived'): raise IPCError('已归档会话不参与内容搜索')
        params['threadId'] = thread_id
    else:
        params.update(sortKey='recency_at', sortDirection='desc', archived=False)
    if authorize: authorize()
    with reader(bridge) as (runtime, verify):
        result = runtime.rpc('thread/searchOccurrences' if thread_id else 'thread/search', params)
        verify()
        if authorize: authorize()
        if not isinstance(result, dict) or not isinstance(result.get('data'), list): raise IPCError('原生搜索回执格式无效')
        cursor = result.get('nextCursor')
        if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096): raise IPCError('原生搜索游标无效')
        if thread_id:
            if record(bridge, thread_id).get('archived'): raise IPCError('搜索期间会话已归档')
            verify()
            if authorize: authorize()
            return {'occurrences': result['data'], 'nextCursor': cursor, 'threadId': thread_id}
        rows = []
        for item in result['data']:
            thread = item.get('thread') if isinstance(item, dict) else None
            if not isinstance(thread, dict): raise IPCError('原生搜索会话格式无效')
            tid = valid_id(thread.get('id'))
            try: native = record(bridge, tid)
            except (IPCError, ValueError): continue
            if native.get('archived'): continue
            rows.append({'id': tid, 'title': native.get('name') or native.get('title') or '未命名会话', 'cwd': native.get('cwd') or '', 'snippet': item.get('snippet', '')})
        verify()
        if authorize: authorize()
        return {'threads': rows, 'nextCursor': cursor}


def anchor(bridge, thread_id, query, authorize=None):
    """Count the native tail after an inclusive occurrence cursor for the history window."""
    valid_id(thread_id)
    def eligible():
        if record(bridge, thread_id).get('archived'): raise IPCError('已归档会话不参与内容搜索')
    eligible()
    values = {}
    for key in ('turnCursor', 'turnId', 'itemId'):
        value = query.get(key, [''])[0]
        if not value or len(value) > (4096 if key == 'turnCursor' else 200) or '\x00' in value:
            raise ValueError('搜索命中身份无效')
        values[key] = value
    if authorize: authorize()
    count, cursor, seen, first = 0, values['turnCursor'], set(), True
    with reader(bridge) as (runtime, verify):
        while True:
            verify()
            if authorize: authorize()
            page = runtime.rpc('thread/turns/list', {'threadId': thread_id, 'cursor': cursor,
                'sortDirection': 'asc', 'limit': 1 if first else 100, 'itemsView': 'full' if first else 'summary'})
            verify()
            turns = page.get('data') if isinstance(page, dict) else None
            if not isinstance(turns, list): raise IPCError('原生搜索历史回执格式无效')
            if first:
                if (len(turns) != 1 or turns[0].get('id') != values['turnId']
                        or not any(item.get('id') == values['itemId'] for item in turns[0].get('items', []))):
                    raise IPCError('搜索命中与原生历史不匹配，请重新搜索')
                first = False
            count += len(turns)
            if count > 4000: raise IPCError('该命中超出当前历史窗口范围')
            cursor = page.get('nextCursor')
            if cursor is None: break
            if not isinstance(cursor, str) or not cursor or cursor in seen or not turns:
                raise IPCError('原生历史分页游标无效')
            seen.add(cursor)
        eligible(); verify()
        if authorize: authorize()
        return {'threadId': thread_id, 'turnId': values['turnId'], 'itemId': values['itemId'], 'historyLimit': count}
