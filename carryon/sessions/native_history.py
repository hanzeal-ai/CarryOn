"""Canonical public persisted messages, without loading or resuming their task."""
import json
import threading
from collections import OrderedDict
from pathlib import Path
from carryon.app_server.read_control import reader
from carryon.app_server.app_server import native_turn
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.history_cache import NativeSnapshot


class NativeHistory:
    def __init__(self):
        self.lock = threading.RLock()
        self.entries = OrderedDict()
        self.bytes = 0

    def clear(self):
        with self.lock: self.entries.clear(); self.bytes = 0

    def read(self, bridge, row, limit):
        from carryon.sessions.bridge import snapshot_history
        ipc, generation = bridge.require()
        tid = row['id']; limit = limit or 4000
        path = Path(row['rollout_path']).resolve()
        if not path.is_relative_to(bridge.catalog.home): raise IPCError('会话历史路径无效')
        info = path.stat()
        service = getattr(bridge, 'owner_service', None)
        transport = ipc.session_id if getattr(ipc, 'protocol', None) == 'codex-app-server' else ipc.client_id
        key = (generation, transport, id(service), tid, limit, info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size, row.get('name'), row.get('title'), row.get('cwd'))
        with self.lock:
            cached = self.entries.get(key)
            if cached is not None: self.entries.move_to_end(key)
        if cached is not None:
            if bridge.catalog.archive_record(tid).get('archived'): raise IPCError('读取期间会话已归档')
            with bridge.lock:
                bridge.check_generation(ipc, generation)
                current_transport = ipc.session_id if getattr(ipc, 'protocol', None) == 'codex-app-server' else ipc.client_id
                if current_transport != transport: raise IPCError('历史读取期间原生连接已改变')
                if service is not None and (getattr(bridge, 'owner_service', None) is not service or service.closed.is_set()): raise IPCError('历史读取期间工作区归属已改变')
            return dict(cached[0])
        with reader(bridge) as (runtime, verify):
            thread = runtime.rpc('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
            if thread.get('id') != tid: raise IPCError('原生历史会话身份不匹配')
            turns, cursor, seen = [], None, set()
            while len(turns) < limit:
                page = runtime.rpc('thread/turns/list', {'threadId': tid, 'sortDirection': 'desc', 'limit': min(100, limit - len(turns)), 'itemsView': 'full', **({'cursor': cursor} if cursor else {})})
                verify()
                data = page.get('data') if isinstance(page, dict) else None
                if not isinstance(data, list): raise IPCError('原生历史回执格式无效')
                turns.extend(native_turn(turn) for turn in data)
                cursor = page.get('nextCursor')
                if cursor is None: break
                if not isinstance(cursor, str) or not cursor or cursor in seen or not data: raise IPCError('原生历史分页游标无效')
                seen.add(cursor)
            verify()
            if bridge.catalog.archive_record(tid).get('archived'): raise IPCError('读取期间会话已归档')
            state = NativeSnapshot({'id': tid, 'title': thread.get('name') or row.get('name') or row.get('title') or '', 'cwd': thread.get('cwd') or row.get('cwd'), 'threadMetadata': thread, 'turns': list(reversed(turns)), 'threadRuntimeStatus': {'type': 'notLoaded'}, 'requests': []})
            result = snapshot_history(state)
            result.update(source='native-persisted', controls={}, pendingRequests=[], access={'nativeReady': False, 'canInteract': False}, historyWindow={'limit': limit, 'hasMore': cursor is not None, 'unit': 'turns'}, historyRevision='native-read:' + state.history_revision)
        # Reuse only a stable native file version; never cache across a concurrent write.
        after = path.stat()
        if (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size) == (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size):
            size = len(json.dumps(result, ensure_ascii=False).encode())
            if size <= 4 * 1024 * 1024:
                with self.lock:
                    previous = self.entries.pop(key, None)
                    if previous: self.bytes -= previous[1]
                    self.entries[key] = (result, size); self.bytes += size
                    while len(self.entries) > 8 or self.bytes > 4 * 1024 * 1024:
                        _, (_, old_size) = self.entries.popitem(last=False); self.bytes -= old_size
        return dict(result)
