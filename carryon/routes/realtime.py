"""Bridge-owned live projections and shared native subscription lifecycle."""
import logging
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from carryon.sessions.catalog import valid_id
from carryon.errors import BridgeError
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.thread_status import project_status


class Realtime:
    def __init__(self, bridge):
        self.bridge = bridge
        self.sessions = set()
        self.watched = {}
        self.unavailable = {}
        self.load_attempts = {}
        self.load_sequence = 0
        self.refresh_threads = set()
        self.closed = threading.Event()
        self.workers = []
        self.load_event = threading.Event()

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
                if hasattr(self.bridge,'workspace'):desired.update(self.bridge.workspace.thread_ids())
                desired.update(j['threadId'] for j in self.bridge.journal.list(limit=100)
                               if (j['kind'] == 'create' and not j.get('createdThreadId') and j['state'] == 'accepted' and j.get('turnId')
                                   or j['state'] == 'uncertain' and (j.get('turnId') or j.get('clientMessageId'))))
            for tid, source in list(self.watched.items()):
                if tid not in desired or source is not ipc:
                    source.unwatch(tid)
                    del self.watched[tid]
                    self.unavailable.pop(tid, None)
                    self.load_attempts.pop(tid, None)
                    self.refresh_threads.discard(tid)
            for tid in desired:
                if tid not in self.watched:
                    ipc.watch(tid)
                    self.watched[tid] = ipc

    def thread_status(self, tid, ipc, native):
        """HTTP lists and live rows use the same native evidence and probe result."""
        with self.bridge.lock:
            previous = self.unavailable.get(tid)
            if native is not None:
                return project_status(native)
            if previous and previous[0] is ipc and previous[2]:
                return dict(previous[2])
        return {'state': 'loading', 'label': '检测中'}

    def _status_changed(self):
        workspace = getattr(self.bridge, 'workspace', None)
        if workspace is not None:
            workspace.invalidate_status()
        else:
            self.bridge.notify()

    def refresh_statuses(self, ids):
        """Retry missing snapshots without resuming tasks or discarding live state."""
        changed = False
        with self.bridge.lock:
            ipc = self.bridge.ipc
            for tid in ids:
                native = ipc.current(tid) if ipc else None
                if native is not None and not native.get('_metadataOnly'):
                    continue
                changed |= self.unavailable.pop(tid, None) is not None
                self.refresh_threads.add(tid)
            self.load_event.set()
        if changed:
            self._status_changed()

    def _load_candidates(self, pending):
        """Prefer visible rows; within each tier, untouched/oldest probes go first."""
        with self.bridge.lock:
            selected = {s.selection['threadId'] for s in self.sessions if s.selection['threadId']}
            visible = {tid for s in self.sessions for tid in s.selection['threadIds']}
            visible.update(self.refresh_threads)
            candidates = []
            now = time.monotonic()
            for tid, ipc in self.watched.items():
                previous = self.unavailable.get(tid)
                state = ipc.current(tid)
                if (tid in pending or (state is not None and not state.get('_metadataOnly')) or
                    previous and previous[0] is ipc and now - previous[1] < 30):
                    continue
                tier = 0 if tid in selected else 1 if tid in visible else 2
                candidates.append((tier, self.load_attempts.get(tid, -1), tid))
            candidates.sort()
            slots = max(0, 4 - len(pending))
            # Keep background discovery moving even while foreground misses retry.
            background = [row[2] for row in candidates if row[0] == 2]
            ids = [row[2] for row in candidates[:slots]]
            if slots and background and not any(tid not in selected | visible for tid in pending):
                if ids and all(tid in selected | visible for tid in ids):
                    ids[-1] = background[0]
            for tid in ids:
                self.load_sequence += 1
                self.load_attempts[tid] = self.load_sequence
                self.refresh_threads.discard(tid)
            return ids

    def _load(self, tid):
        with self.bridge.lock:
            ipc = self.watched.get(tid)
            state = ipc.current(tid) if ipc else None
            if self.closed.is_set() or ipc is None or state is not None and not state.get('_metadataOnly'):
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
            previous = self.unavailable.get(tid)
            self.unavailable[tid] = (ipc, time.monotonic(), result)
            changed = previous is None or previous[0] is not ipc or previous[2] != result
        if changed:
            self._status_changed()
        else:
            self.bridge.notify()

    def _load_sidebar(self):
        # Bounded submissions, no blocking map over the entire directory. A newly
        # selected conversation takes the next free slot ahead of sidebar work.
        pending = {}
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='sidebar-status') as pool:
            while not self.closed.is_set():
                self.load_event.wait(.25)
                self.load_event.clear()
                if self.closed.is_set(): break
                pending = {tid: future for tid, future in pending.items() if not future.done()}
                self.sync_watches()
                for tid in self._load_candidates(pending):
                    pending[tid] = pool.submit(self._load, tid)

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
            for job in self.bridge.journal.list(limit=100):
                if self.closed.is_set():
                    return
                if (job['kind'] == 'create' and not job.get('createdThreadId') and job['state'] == 'accepted' and job.get('turnId')
                        or job['state'] == 'uncertain' and (job.get('turnId') or job.get('clientMessageId'))):
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
        self.next_update_at = 0
        self.side_ids = set()
        self.persisted_history = False
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
        limit = message.get('historyLimit')
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 100000):
            raise ValueError('Invalid history limit')
        side_limit = message.get('sideHistoryLimit', limit)
        if side_limit is not None and (type(side_limit) is not int or not 1 <= side_limit <= 100000):
            raise ValueError('Invalid side history limit')
        protocol = message.get('historyProtocol') == 1
        with self.bridge.lock:
            if self.closed:
                return
            self.selection = {'subscription': subscription, 'threadId': target, 'threadIds': ids,
                              'includeSideChats': include_sides, 'sideThreadId': side_id,
                              'historyLimit': limit, 'sideHistoryLimit': side_limit, 'historyProtocol': int(protocol)}
            self.side_ids.clear()
            self.persisted_history = False
            self.version += 1
            self.owner.sync_watches()
            self.owner.load_event.set()
        self.bridge.notify()

    def wait(self, revision):
        with self.bridge.events:
            if revision == self.bridge.event_revision and not self.closed:
                self.bridge.events.wait(1 if self.persisted_history else 15)
            revision = self.bridge.event_revision
        # Coalesce token bursts; each stream holds only its newest pending projection.
        remaining = self.next_update_at - time.monotonic()
        if remaining > 0:
            self.owner.closed.wait(remaining)
        self.next_update_at = time.monotonic() + .05
        return revision

    def update(self):
        with self.bridge.lock:
            selection, version = dict(self.selection), self.version
            status = self.bridge.status()
            ipc, generation = self.bridge.require() if status['enabled'] else (None, None)
        target, ids = selection['threadId'], selection['threadIds']
        packet = {'type': 'update', 'status': status, 'threadId': target,
                  'subscription': selection['subscription'], 'historyProtocol': selection.get('historyProtocol', 0)}
        if ipc:
            self.owner.sync_watches()
            if hasattr(self.bridge,'workspace'):packet['workspaceRevision']=self.bridge.workspace.revision
            packet['jobs'] = self.bridge.journal.list(limit=100)
            packet['threadStatuses'] = {}
            for tid in ids:
                packet['threadStatuses'][tid] = self.owner.thread_status(tid, ipc, ipc.current(tid))
            if hasattr(ipc, 'events'):
                with ipc.lock:
                    packet['catalogRevision'] = ipc.events.catalog_revision
                    packet['threadFlags'] = {}
                    for tid in ids:
                        native = ipc.current(tid) or {}
                        flags = dict(ipc.events.flags.get(tid, {}))
                        if type(native.get('hasUnreadTurn')) is bool:
                            flags['hasUnreadTurn'] = native['hasUnreadTurn']
                        packet['threadFlags'][tid] = flags
            if target and selection['includeSideChats']:
                packet['sideChats'] = self.bridge.side_chats(target)
                with self.bridge.lock:
                    if not self.closed and version == self.version:
                        self.side_ids = {chat['id'] for chat in packet['sideChats']['chats']}
                        self.owner.sync_watches()
            if target:
                try:
                    if hasattr(self.bridge,'workspace'):packet['readSequence']=self.bridge.workspace.latest_sequence(target)
                    history = self.bridge.history(target, limit=selection['historyLimit']) if selection.get('historyLimit') else self.bridge.history(target)
                    packet['history'] = history
                    with self.bridge.lock:
                        if version == self.version:
                            self.persisted_history = history.get('source') == 'local-rollout'
                except (ValueError, OSError, IPCError) as exc:
                    packet['error'] = str(exc)
            if target and selection['includeSideChats'] and selection['sideThreadId']:
                packet['sideThreadId'] = selection['sideThreadId']
                try:
                    history = (self.bridge.side_history(target, selection['sideThreadId'], limit=selection['sideHistoryLimit'])
                               if selection.get('sideHistoryLimit') else self.bridge.side_history(target, selection['sideThreadId']))
                    packet['sideHistory'] = history
                except (ValueError, OSError, IPCError) as exc:
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
        # Admission is checked under the authority lock; socket I/O must not hold it.
        # Each transport writer has at most one admitted packet in flight.
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


def packet_signature(packet):
    """Unchanged native histories compare by revision, without re-encoding their bodies."""
    compact = dict(packet)
    for field in ('history', 'sideHistory'):
        history = compact.get(field)
        if isinstance(history, dict) and history.get('historyRevision'):
            compact[field] = history['historyRevision']
    return json.dumps(compact, ensure_ascii=False, sort_keys=True)
