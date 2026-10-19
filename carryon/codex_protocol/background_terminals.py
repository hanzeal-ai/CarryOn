"""Live native terminal inventory belongs to its owning process, never a short reader."""
from carryon.errors import IPCError


def identity(runtime, tid):
    state = runtime.current(tid)
    if not runtime.connected or not state or state.get('id') != tid or state.get('_metadataOnly'):
        raise IPCError('后台终端需要实际拥有会话的原生进程')
    return runtime.connection_identity


def verify(runtime, tid, expected):
    if identity(runtime, tid) != expected: raise IPCError('后台终端所属原生进程已改变')


def page(runtime, tid, limit=50, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 100: raise ValueError('终端页大小须为1–100')
    if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096): raise ValueError('终端游标无效')
    expected = identity(runtime, tid)
    result = runtime.rpc('thread/backgroundTerminals/list', {'threadId': tid, 'limit': limit, **({'cursor': cursor} if cursor else {})}, timeout_ms=3000)
    verify(runtime, tid, expected)
    if not isinstance(result, dict) or not isinstance(result.get('data'), list) or 'nextCursor' not in result: raise IPCError('原生后台终端回执无效')
    next_cursor = result['nextCursor']
    if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 4096): raise IPCError('原生后台终端游标无效')
    rows = result['data']
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('processId'), str) or not 0 < len(row['processId']) <= 256 or not isinstance(row.get('itemId'), str) or not isinstance(row.get('command'), str) or not isinstance(row.get('cwd'), str): raise IPCError('原生后台终端记录无效')
    if len({row['processId'] for row in rows}) != len(rows): raise IPCError('原生后台终端身份重复')
    return {'terminals': rows, 'nextCursor': next_cursor}, expected


def empty(runtime, tid):
    result, expected = page(runtime, tid, limit=1)
    if result['terminals'] or result['nextCursor'] is not None: raise IPCError('cannot release a session with background terminals')
    return expected
