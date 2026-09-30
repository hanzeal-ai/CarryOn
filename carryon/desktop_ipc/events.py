"""Desktop coordination notifications, separate from versioned history patches."""
import copy
import threading

from carryon.sessions.catalog import ID

VERSIONS = {'thread-stream-following-status-requested': 1, 'ipc-connection-reset': 1,
            'thread-read-state-changed': 3, 'thread-archived': 2,
            'thread-unarchived': 1, 'thread-queued-followups-changed': 2}


class Events:
    def __init__(self, ipc):
        self.ipc = ipc
        self.queues = {}
        self.flags = {}
        self.catalog_revision = 0
        self.reset_revision = 0
        self.read_refreshes = {}
        self.read_dirty = set()

    def clear(self):
        self.read_refreshes.clear()
        self.read_dirty.clear()
        self.queues.clear()
        self.flags.clear()
        self.catalog_revision += 1

    def handle(self, message):
        method = message.get('method')
        if method not in VERSIONS or message.get('version') != VERSIONS[method]:
            return
        ipc = self.ipc
        params = message.get('params', {})
        source = message.get('sourceClientId')
        if not isinstance(params, dict) or not isinstance(source, str) or not source:
            return
        if method == 'ipc-connection-reset':
            with ipc.changed:
                self.clear(); self.reset_revision += 1
                ipc.snapshots.clear()
                for waiter in ipc.pending.values():
                    waiter['error'] = 'IPC 连接已重置；已投递操作的结果可能未知，不会自动重发'
                    waiter['event'].set()
                targets = list(ipc.following)
                ipc.changed.notify_all()
            ipc.on_change()
            def restore():
                for tid in targets:
                    if not ipc.connected:
                        break
                    ipc._resync(tid)
            threading.Thread(target=restore, daemon=True).start()
            return
        tid = params.get('conversationId')
        host = params.get('hostId')
        if host != 'local' or not isinstance(tid, str) or not ID.fullmatch(tid):
            return
        if method == 'thread-read-state-changed':
            # v3 is identity-scoped. Treat it only as an invalidation; the
            # followed owner supplies the authoritative flag for this connection.
            if type(params.get('hasUnreadTurn')) is not bool or not isinstance(params.get('context'), dict):
                return
            self.refresh_read(tid)
            return
        with ipc.lock:
            owner = ipc.following.get(tid)
            if method == 'thread-stream-following-status-requested':
                if owner != source:
                    return
                ipc._write({'type': 'broadcast', 'method': 'thread-stream-following-changed',
                    'version': 1, 'sourceClientId': ipc.client_id, 'targetClientIds': [source],
                    'params': {'hostId': 'local', 'conversationId': tid, 'following': True}})
                return
            if method == 'thread-queued-followups-changed':
                if owner != source or owner is None:
                    return
                messages = params.get('messages')
                from carryon.sessions.queue import projection
                try:
                    projection(messages, 'desktop-broadcast')
                except ValueError:
                    self.queues.pop(tid, None)
                else:
                    self.queues[tid] = copy.deepcopy(messages)
            else:
                self.flags.setdefault(tid, {})['archived'] = method == 'thread-archived'
                self.catalog_revision += 1
            # Notifications are an in-memory projection, never writes to Codex state.
            for store in (self.queues, self.flags):
                while len(store) > 500:
                    del store[next(iter(store))]
        ipc.on_change()

    def refresh_read(self, tid):
        ipc = self.ipc
        with ipc.lock:
            if tid not in ipc.following:
                return
            self.read_dirty.add(tid)
            if tid in self.read_refreshes:
                return
            token = object()
            self.read_refreshes[tid] = token
        threading.Thread(target=self._refresh_read, args=(tid, token), daemon=True).start()

    def _refresh_read(self, tid, token):
        from carryon.desktop_ipc.ipc import IPCError
        ipc = self.ipc
        try:
            while True:
                with ipc.lock:
                    if self.read_refreshes.get(tid) is not token or tid not in ipc.following:
                        return
                    self.read_dirty.discard(tid)
                owner, _ = ipc.snapshot(tid)
                with ipc.lock:
                    if self.read_refreshes.get(tid) is not token or ipc.following.get(tid) != owner:
                        return
                    if tid in self.read_dirty:
                        continue
                    current = ipc.current(tid) or {}
                    unread = current.get('hasUnreadTurn')
                    if type(unread) is bool:
                        self.flags.setdefault(tid, {})['hasUnreadTurn'] = unread
                        while len(self.flags) > 500:
                            del self.flags[next(iter(self.flags))]
                if unread is False:
                    ipc.on_read(tid, current, token)
                ipc.on_change()
                with ipc.lock:
                    if tid not in self.read_dirty:
                        if self.read_refreshes.get(tid) is token:
                            self.read_refreshes.pop(tid, None)
                        return
        except (IPCError, OSError, ValueError):
            # A lost owner cannot authorize clearing a read cursor.
            pass
        finally:
            with ipc.lock:
                if self.read_refreshes.get(tid) is token:
                    self.read_refreshes.pop(tid, None)
                    self.read_dirty.discard(tid)
