"""Desktop coordination notifications, separate from versioned history patches."""
import copy
import threading

from .catalog import ID

VERSIONS = {'thread-stream-following-status-requested': 1, 'ipc-connection-reset': 1,
            'thread-read-state-changed': 2, 'thread-archived': 2,
            'thread-unarchived': 1, 'thread-queued-followups-changed': 1}


class Events:
    def __init__(self, ipc):
        self.ipc = ipc
        self.queues = {}
        self.flags = {}
        self.catalog_revision = 0
        self.reset_revision = 0

    def clear(self):
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
        host = params.get('hostId', 'local' if method == 'thread-queued-followups-changed' else None)
        if host != 'local' or not isinstance(tid, str) or not ID.fullmatch(tid):
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
                from .queue import projection
                try:
                    projection(messages, 'desktop-broadcast')
                except ValueError:
                    self.queues.pop(tid, None)
                else:
                    self.queues[tid] = copy.deepcopy(messages)
            elif method == 'thread-read-state-changed':
                if type(params.get('hasUnreadTurn')) is not bool:
                    return
                self.flags.setdefault(tid, {})['hasUnreadTurn'] = params['hasUnreadTurn']
            else:
                self.flags.setdefault(tid, {})['archived'] = method == 'thread-archived'
                self.catalog_revision += 1
            # Notifications are an in-memory projection, never writes to Codex state.
            for store in (self.queues, self.flags):
                while len(store) > 500:
                    del store[next(iter(store))]
        ipc.on_change()
