"""Bridge-owned live projections and shared native subscription lifecycle."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .catalog import valid_id
from .errors import BridgeError
from .ipc import IPCError
from .thread_status import project_status


class Realtime:
    def __init__(self, bridge):
        self.bridge = bridge
        self.sessions = set()
        self.watched = {}
        self.unavailable = {}
        self.closed = threading.Event()
        self.workers = []

    def open(self):
        with self.bridge.lock:
            session = Subscription(self)
            self.sessions.add(session)
            if not self.workers:
                for run in (self._load_sidebar, self._reconcile):
                    worker = threading.Thread(target=run, daemon=True)
                    self.workers.append(worker)
                    worker.start()
            return session

    def sync_watches(self):
        """One native watch per thread, shared by all live consumers."""
        with self.bridge.lock:
            ipc = self.bridge.ipc if self.bridge.status()['enabled'] and not self.closed.is_set() else None
            desired = set()
            if ipc:
                for session in self.sessions:
                    selection = session.selection
                    desired.update(selection['threadIds'])
                    if selection['threadId']:
                        desired.add(selection['threadId'])
                    desired.update(session.side_ids)
                desired.update(j['threadId'] for j in self.bridge.journal.list()[:100]
                               if j['state'] in ('accepted', 'uncertain') and j.get('turnId'))
            for tid, source in list(self.watched.items()):
                if tid not in desired or source is not ipc:
                    source.unwatch(tid)
                    del self.watched[tid]
                    self.unavailable.pop(tid, None)
            for tid in desired:
                if tid not in self.watched:
                    ipc.watch(tid)
                    self.watched[tid] = ipc

    def _load(self, tid):
        with self.bridge.lock:
            ipc = self.watched.get(tid)
            if self.closed.is_set() or ipc is None or ipc.current(tid) is not None:
                return
            previous = self.unavailable.get(tid)
            if previous and previous[0] is ipc and time.monotonic() - previous[1] < 30:
                return
        try:
            ipc.sidebar_snapshot(tid)
            result = None
        except (IPCError, OSError, ValueError) as error:
            # Only a confirmed routing miss means not loaded.
            result = ({'state': 'notLoaded', 'label': '未加载'} if str(error) == 'no-client-found'
                      else {'state': 'unknown', 'label': '状态未知'})
        with self.bridge.lock:
            if self.closed.is_set() or self.watched.get(tid) is not ipc or self.bridge.ipc is not ipc:
                return
            self.unavailable[tid] = (ipc, time.monotonic(), result)
        self.bridge.notify()

    def _load_sidebar(self):
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='sidebar-status') as pool:
            while not self.closed.wait(1):
                self.sync_watches()
                with self.bridge.lock:
                    ids = {tid for s in self.sessions for tid in s.selection['threadIds']}
                list(pool.map(self._load, ids))

    def _reconcile(self):
        """Slow evidence reads never run on a client's transport writer."""
        revision = -1
        while not self.closed.is_set():
            with self.bridge.events:
                if revision == self.bridge.event_revision:
                    self.bridge.events.wait(15)
                revision = self.bridge.event_revision
            if self.closed.is_set():
                return
            self.sync_watches()
            if not self.bridge.status()['enabled']:
                continue
            for job in self.bridge.journal.list()[:100]:
                if self.closed.is_set():
                    return
                if job['state'] in ('accepted', 'uncertain') and job.get('turnId'):
                    try:
                        self.bridge.refresh_job(job['id'])
                    except (ValueError, OSError, IPCError, BridgeError):
                        continue
                    except Exception as exc:
                        logging.getLogger(__name__).error('Job reconciliation failed (%s)', type(exc).__name__)


class Subscription:
    def __init__(self, owner):
        self.owner = owner
        self.bridge = owner.bridge
        self.closed = False
        self.version = 0
        self.side_ids = set()
        self.selection = {'threadId': None, 'subscription': None, 'threadIds': [],
                          'includeSideChats': False, 'sideThreadId': None}

    def subscribe(self, message):
        if message.get('type') != 'subscribe':
            raise ValueError('Unknown stream request')
        subscription = message.get('subscription')
        if not isinstance(subscription, str) or len(subscription) > 100:
            raise ValueError('Invalid subscription')
        target = message.get('threadId')
        if target is not None:
            valid_id(target)
        ids = message.get('threadIds', [])
        if not isinstance(ids, list) or len(ids) > 100:
            raise ValueError('Maximum 100 sidebar threads')
        ids = list(dict.fromkeys(valid_id(tid) for tid in ids))
        include_sides = message.get('includeSideChats', False)
        if type(include_sides) is not bool:
            raise ValueError('Invalid side chat flag')
        side_id = message.get('sideThreadId')
        if side_id is not None:
            valid_id(side_id)
        if side_id and (not include_sides or not target):
            raise ValueError('Side chat requires parent')
        with self.bridge.lock:
            if self.closed:
                return
            self.selection = {'subscription': subscription, 'threadId': target, 'threadIds': ids,
                              'includeSideChats': include_sides, 'sideThreadId': side_id}
            self.side_ids.clear()
            self.version += 1
            self.owner.sync_watches()
        self.bridge.notify()

    def wait(self, revision):
        with self.bridge.events:
            if revision == self.bridge.event_revision and not self.closed:
                self.bridge.events.wait(15)
            return self.bridge.event_revision

    def update(self):
        with self.bridge.lock:
            selection, version = dict(self.selection), self.version
            status = self.bridge.status()
            ipc, generation = self.bridge.require() if status['enabled'] else (None, None)
        target, ids = selection['threadId'], selection['threadIds']
        packet = {'type': 'update', 'status': status, 'threadId': target,
                  'subscription': selection['subscription']}
        if ipc:
            self.owner.sync_watches()
            packet['jobs'] = self.bridge.journal.list()[:100]
            with self.bridge.lock:
                missing = dict(self.owner.unavailable)
            packet['threadStatuses'] = {}
            for tid in ids:
                native = ipc.current(tid)
                unavailable = missing.get(tid)
                packet['threadStatuses'][tid] = (project_status(native) if native is not None else
                    unavailable[2] if unavailable and unavailable[0] is ipc and unavailable[2] else
                    {'state': 'loading', 'label': '检测中'})
            if hasattr(ipc, 'events'):
                with ipc.lock:
                    packet['catalogRevision'] = ipc.events.catalog_revision
                    packet['threadFlags'] = {}
                    for tid in ids:
                        native = ipc.current(tid) or {}
                        flags = ({'hasUnreadTurn': native['hasUnreadTurn']}
                                 if type(native.get('hasUnreadTurn')) is bool else {})
                        flags.update(ipc.events.flags.get(tid, {}))
                        packet['threadFlags'][tid] = flags
            if target and selection['includeSideChats']:
                packet['sideChats'] = self.bridge.side_chats(target)
                with self.bridge.lock:
                    if not self.closed and version == self.version:
                        self.side_ids = {chat['id'] for chat in packet['sideChats']['chats']}
                        self.owner.sync_watches()
            if target:
                try:
                    history = self.bridge.history(target)
                    packet['history'] = {k: v for k, v in history.items() if k != 'turns'}
                except (ValueError, IPCError) as exc:
                    packet['error'] = str(exc)
            if target and selection['includeSideChats'] and selection['sideThreadId']:
                packet['sideThreadId'] = selection['sideThreadId']
                try:
                    history = self.bridge.side_history(target, selection['sideThreadId'])
                    packet['sideHistory'] = {k: v for k, v in history.items() if k != 'turns'}
                except (ValueError, IPCError) as exc:
                    packet['sideError'] = str(exc)
        return packet, version, ipc, generation

    def deliver(self, update, send):
        packet, version, ipc, generation = update
        with self.bridge.lock:
            if self.closed or version != self.version:
                return
            if ipc is not None:
                self.bridge.check_generation(ipc, generation)
            elif self.bridge.status()['enabled']:
                return
            send(packet)

    def close(self):
        with self.bridge.lock:
            if self.closed:
                return
            self.closed = True
            self.owner.sessions.discard(self)
            if not self.owner.sessions:
                self.owner.closed.set()
            self.owner.sync_watches()
        self.bridge.notify()
