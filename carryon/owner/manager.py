"""Explicit, removable owner service. Each loaded thread owns one runtime lifetime."""
import threading
import weakref
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import time
from pathlib import Path
from collections import OrderedDict, deque
from carryon.app_server.app_server import AppServer
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError
from carryon.sessions.catalog import valid_id
from carryon.contracts import digest
from carryon.owner.requests import APPROVALS, VERSIONS, forward
from carryon.owner.state import conversation
from carryon.owner.prewarm import PrewarmedRuntime


class OwnerManager:
    def __init__(self, home, directory, catalog, *, runtime_factory=AppServer, transport_factory=DesktopIPC):
        self.home, self.directory, self.catalog = Path(home), Path(directory), catalog
        self.runtime_factory = runtime_factory
        self.bus = transport_factory(self.home / 'ipc/ipc.sock')
        self.bus.request_handler = self
        self.lock = threading.RLock()
        self.entries = {}
        self.operation_locks = weakref.WeakValueDictionary()
        self.loading = set()
        self.connect_lock = threading.Lock()
        self.revisions = {}
        self.receipts = {}
        self.follower_events = deque()
        self.follower_lock = threading.RLock()
        self.dirty = threading.Event()
        self.closed = threading.Event()
        self.worker = None
        self.retry_at = 0
        self.prewarm = PrewarmedRuntime(self.home, self.directory / "runtimes", runtime_factory)
        self.prewarm.start()

    def _thread_lock(self, tid):
        with self.lock:
            return self.operation_locks.setdefault(tid, threading.RLock())

    @contextmanager
    def _acquisition(self, tid):
        # Slow discovery/resume serializes only this thread, never the registry.
        with self._thread_lock(tid):
            with self.lock:
                if self.closed.is_set(): raise IPCError('owner-service-closed')
                self.loading.add(tid)
            try:
                yield
            finally:
                with self.lock:
                    self.loading.discard(tid)
                self.dirty.set()

    def _connect_bus(self):
        with self.connect_lock:
            if self.closed.is_set(): raise IPCError('owner-service-closed')
            if not self.bus.connected: self.bus.connect()
            with self.lock:
                if self.closed.is_set():
                    self.bus.close()
                    raise IPCError('owner-service-closed')

    def load(self, tid, authorize=lambda: None):
        valid_id(tid)
        with self._acquisition(tid):
            authorize()
            if self.closed.is_set(): raise IPCError('owner-service-closed')
            if tid in self.entries:
                if self.entries[tid]['conflict']: raise IPCError('owner-conflict')
                if self.entries[tid].get('suspended'):
                    self._resume(tid, authorize)
                if not self.entries[tid]['runtime'].connected or not self.bus.connected:
                    raise IPCError('owner-disconnected; release before loading again')
                return self.describe(tid)
            row = self.catalog.get(tid)
            # Native paginated writer locks are the cross-process exclusion boundary.
            if row.get('history_mode') != 'paginated':
                raise IPCError('owner requires paginated history with native writer locking')
            self._connect_bus()
            try:
                owner = self.bus.owner(tid, timeout_ms=3000)
            except IPCError as exc:
                if str(exc) != 'no-client-found': raise
            else: return {'threadId': tid, 'state': 'desktop', 'owner': owner}
            runtime = self.prewarm.take()
            runtime.on_change = self.dirty.set
            try:
                authorize()
                _, state = runtime.snapshot(tid)
                if state['threadRuntimeStatus']['type'] != 'idle' or state.get('requests'):
                    raise IPCError('resume did not produce an idle baseline')
                authorize()
                try: self.bus.owner(tid, timeout_ms=3000)
                except IPCError as exc:
                    if str(exc) != 'no-client-found': raise
                else: raise IPCError('owner appeared during resume')
                if self.closed.is_set(): raise IPCError('owner-service-closed')
                self._register(tid, {'runtime': runtime, 'snapshot': None, 'followers': set(),
                                     'conflict': False, 'receipts': self._receipts(tid),
                                     'disconnect': False, 'initial_turn_ids': {t['turnId'] for t in state['turns']},
                                     'submitted_turn_ids': set(), 'awaiting_new_turn': False,
                                     'recovery_receipts': OrderedDict()})
                self.publish(tid, force=True)
            except Exception:
                with self.lock:
                    self.entries.pop(tid, None)
                    if not self.receipts.get(tid): self.receipts.pop(tid, None)
                runtime.close()
                raise
            self._start_worker()
            return self.describe(tid)

    def _start_worker(self):
        with self.lock:
            if self.closed.is_set(): raise IPCError('owner-service-closed')
            if self.worker is None:
                self.worker = threading.Thread(target=self._pump, daemon=True, name='owner-state-publisher')
                self.worker.start()

    def _receipts(self, tid):
        with self.lock:
            return self.receipts.setdefault(tid, OrderedDict())

    def _register(self, tid, entry):
        with self.lock:
            if self.closed.is_set(): raise IPCError('owner-service-closed')
            self.entries[tid] = entry

    def describe(self, tid):
        entry = self.entries[tid]
        runtime = entry['runtime']
        return {'threadId': tid, 'state': 'conflict' if entry['conflict'] else 'loaded',
                'owner': self.bus.client_id, 'runtimeConnected': runtime.connected}

    def _resume(self, tid, authorize=lambda: None):
        """Reopen a finished writer without changing the follower's owner address."""
        entry = self.entries[tid]
        authorize()
        self.catalog.get(tid)
        if not self.bus.connected or entry['conflict']: raise IPCError('owner-disconnected')
        try: self.bus.owner(tid, timeout_ms=3000)
        except IPCError as exc:
            if str(exc) != 'no-client-found': raise
        else:
            entry['conflict'] = True
            raise IPCError('owner appeared while idle')
        runtime = self.prewarm.take()
        runtime.on_change = self.dirty.set
        try:
            _, state = runtime.snapshot(tid)
            if state['threadRuntimeStatus']['type'] != 'idle' or state.get('requests'):
                raise IPCError('resume did not produce an idle baseline')
            authorize()
            try: self.bus.owner(tid, timeout_ms=3000)
            except IPCError as exc:
                if str(exc) != 'no-client-found': raise
            else: raise IPCError('owner appeared during resume')
            initial_turn_ids = {t['turnId'] for t in state['turns']}
            with self.lock:
                if self.closed.is_set() or self.entries.get(tid) is not entry:
                    raise IPCError('owner-service-closed')
                if entry['conflict']: raise IPCError('owner-conflict')
                entry.update(runtime=runtime, suspended=False, snapshot=None,
                    initial_turn_ids=initial_turn_ids, submitted_turn_ids=set(),
                    awaiting_new_turn=False, recovery_receipts=OrderedDict())
                self.publish(tid, force=True)
        except Exception:
            runtime.close()
            raise

    def adopt(self, tid, runtime, authorize=lambda: None):
        """Own the still-live creator; empty threads cannot be closed and resumed."""
        valid_id(tid)
        with self._acquisition(tid):
            authorize()
            if self.closed.is_set(): raise IPCError('owner-service-closed')
            if tid in self.entries: raise IPCError('conversation-already-owned')
            state = runtime.current(tid)
            if (not runtime.connected or not state or
                    state.get('threadMetadata', {}).get('historyMode') != 'paginated' or
                    state['threadRuntimeStatus']['type'] != 'idle' or state.get('requests') or state['turns']):
                raise IPCError('new conversation has no idle paginated baseline')
            self._connect_bus()
            try: self.bus.owner(tid, timeout_ms=3000)
            except IPCError as exc:
                if str(exc) != 'no-client-found': raise
            else: raise IPCError('owner appeared during creation')
            authorize()
            if self.closed.is_set(): raise IPCError('owner-service-closed')
            runtime.on_change = self.dirty.set
            self._register(tid, {'runtime': runtime, 'snapshot': None, 'followers': set(),
                'conflict': False, 'receipts': self._receipts(tid),
                'disconnect': False, 'initial_turn_ids': set(), 'submitted_turn_ids': set(),
                'awaiting_new_turn': False, 'recovery_receipts': OrderedDict()})
            try:
                self.publish(tid, force=True)
            except Exception:
                with self.lock:
                    self.entries.pop(tid, None)
                    if not self.receipts.get(tid): self.receipts.pop(tid, None)
                raise
            self._start_worker()
            return self.describe(tid)

    def can_handle(self, envelope):
        if self.closed.is_set() or not isinstance(envelope, dict): return False
        method, params = envelope.get('method'), envelope.get('params') or {}
        if not isinstance(params, dict): return False
        if not isinstance(method, str) or type(envelope.get('version')) is not int: return False
        if envelope.get('version') != VERSIONS.get(method) or method not in VERSIONS: return False
        host = params.get('hostId', envelope.get('hostId', 'local'))
        if host != 'local': return False
        if method == 'thread-owner-discovery' and params.get('hostId') != 'local': return False
        # Discovery must not wait on a lock held by a caller waiting for discovery.
        if not isinstance(params.get('conversationId'), str): return False
        entry = self.entries.get(params.get('conversationId'))
        return bool(entry and not entry['conflict'] and not entry['disconnect']
                    and (entry['runtime'].connected or entry.get('suspended')) and self.bus.connected)

    def handle(self, envelope):
        params = envelope.get('params') or {}
        tid = params.get('conversationId') if isinstance(params, dict) else None
        method = envelope.get('method')
        recovery = method in APPROVALS or method == 'thread-follower-interrupt-turn'
        inspection = method in ('thread-owner-discovery', 'thread-follower-load-complete-history')
        # Stops and approvals must remain usable while an execution RPC waits.
        gate = nullcontext() if recovery or inspection else self._thread_lock(tid)
        with gate:
            with self.lock:
                self._drain_followers()
                if not self.can_handle(envelope): raise IPCError('conversation-not-owned')
                entry = self.entries[tid]
                if recovery and entry.get('suspended'): raise IPCError('owned-runtime-not-loaded')
                if inspection:
                    if method == 'thread-owner-discovery': return {'supportsUntrustedAppInput': False}
                    self.publish(tid, force=True)
                    return {'revision': self.revisions[tid]}
                start = params.get('turnStart') or {}
                request = start.get('request') or {} if isinstance(start, dict) else {}
                client_message = request.get('clientUserMessageId') if isinstance(request, dict) else None
                if client_message is not None and not isinstance(client_message, str):
                    raise IPCError('invalid-client-message-id')
                if not isinstance(envelope.get('requestId'), str) or not isinstance(envelope.get('sourceClientId'), str):
                    raise IPCError('invalid-request-identity')
                key = ('start', client_message) if method == 'thread-follower-start-turn' and client_message else (
                    'request', envelope['sourceClientId'], envelope['requestId'])
                fingerprint = digest([method, params])
                receipts = entry['recovery_receipts'] if recovery else entry['receipts']
                if key in receipts:
                    previous = receipts[key]
                    if previous['fingerprint'] != fingerprint: raise IPCError('request-id-content-mismatch')
                    if previous.get('error'): raise IPCError(previous['error'], uncertain=previous['uncertain'])
                    self._submitted(entry, method, previous['result'])
                    return deepcopy(previous['result'])
                if recovery:
                    if len(receipts) >= 1000:
                        # Never evict an in-flight receipt and permit a duplicate dispatch.
                        settled = next((k for k, v in receipts.items() if not v.get('pending')), None)
                        if settled is None: raise IPCError('owner-busy')
                        receipts.pop(settled)
                elif sum(len(values) for values in self.receipts.values()) >= 1000:
                    raise IPCError('owner receipt limit reached; restart service after checking prior requests')
                receipt = {'fingerprint': fingerprint, 'error': 'request outcome unknown; do not resend',
                           'uncertain': True, 'pending': True}
                receipts[key] = receipt
                entry['in_flight'] = entry.get('in_flight', 0) + 1
            try:
                if entry.get('suspended'): self._resume(tid)
                with self.lock:
                    if not self.can_handle(envelope) or self.entries.get(tid) is not entry:
                        raise IPCError('conversation-not-owned')
                    runtime = entry['runtime']
                result = forward(runtime, tid, method, params)
                with self.lock:
                    receipt.update(result=deepcopy(result), error=None, uncertain=False)
                    self._submitted(entry, method, result)
                return result
            except Exception as exc:
                with self.lock:
                    receipt.update(error=str(exc), uncertain=isinstance(exc, IPCError) and exc.uncertain)
                    if receipt['uncertain'] and method in ('thread-follower-start-turn', 'thread-follower-compact-thread'):
                        entry['awaiting_new_turn'] = True
                raise
            finally:
                with self.lock:
                    receipt['pending'] = False
                    entry['in_flight'] -= 1
                self.dirty.set()

    @staticmethod
    def _submitted(entry, method, result):
        if method == 'thread-follower-start-turn':
            entry['submitted_turn_ids'].add(result['result']['turn']['id'])
        elif method == 'thread-follower-compact-thread':
            entry['awaiting_new_turn'] = True

    def _release_finished(self):
        # Serialize with new requests; do not close the bus before their replies are sent.
        with self.lock, self.follower_lock:
            self._drain_followers()
            if self.bus.requests_in_flight: return
            for tid, entry in list(self.entries.items()):
                if tid in self.loading or entry.get('in_flight'): continue
                if entry.get('suspended'):
                    if not self.bus.connected or not entry['followers']: self.release(tid)
                    continue
                state = entry['runtime'].current(tid)
                if not entry['runtime'].connected or not state: continue
                if state['threadRuntimeStatus']['type'] != 'idle' or state.get('requests'): continue
                turns = state['turns']
                if any(t['status'] == 'inProgress' for t in turns): continue
                watched = entry['submitted_turn_ids']
                if entry['awaiting_new_turn']:
                    watched = watched | ({t['turnId'] for t in turns} - entry['initial_turn_ids'])
                terminal = {t['turnId'] for t in turns if t['status'] in ('completed', 'failed', 'interrupted')}
                if watched and watched <= terminal:
                    try:
                        if self.bus.connected and entry['followers']:
                            # Keep the routable owner, but release the native writer
                            # so desktop archival remains possible between turns.
                            self.publish(tid, force=True)
                            self._assert_releasable(tid, entry)
                            entry['suspended'] = True
                            entry['runtime'].close()
                        else: self.release(tid)
                    except IPCError:
                        continue  # Native state changed; retry without stopping other owners.

    def broadcast(self, message):
        params = message.get('params') or {}
        if not isinstance(params, dict): return
        if message.get('method') == 'client-status-changed' and params.get('status') == 'disconnected':
            client = params.get('clientId')
            if not isinstance(client, str) or not client: return
            with self.follower_lock:
                self.follower_events.append((None, client, False))
            self.dirty.set()
            return
        tid = params.get('conversationId')
        if not isinstance(tid, str): return
        entry = self.entries.get(tid)
        if not entry or message.get('sourceClientId') == self.bus.client_id: return
        if params.get('hostId') != 'local': return
        method = message.get('method')
        if method == 'thread-stream-following-changed' and message.get('version') == 1:
            source = message.get('sourceClientId')
            if not isinstance(source, str) or not source or type(params.get('following')) is not bool: return
            with self.follower_lock:
                self.follower_events.append((tid, source, params['following']))
            self.dirty.set()
        elif method == 'thread-stream-state-changed' and message.get('version') == 11:
            # Freeze writes on competing owner evidence; keep the runtime under supervision.
            entry['conflict'] = True
            self.dirty.set()

    def _drain_followers(self):
        # The IPC reader cannot acquire the manager lock: a manager operation
        # may be waiting for a response on that reader. Apply notifications here.
        with self.follower_lock:
            while self.follower_events:
                tid, source, following = self.follower_events.popleft()
                entries = [self.entries[tid]] if tid in self.entries else self.entries.values() if tid is None else ()
                for entry in entries:
                    if following: entry['followers'].add(source)
                    else: entry['followers'].discard(source)

    def publish(self, tid, force=False):
        with self.lock:
            entry = self.entries[tid]
            if not self.bus.connected: return
            raw = None if entry.get('suspended') else entry['runtime'].current(tid)
            if raw is None:
                if entry['snapshot'] is None: return
                state = deepcopy(entry['snapshot'])
            else:
                state = conversation(raw)
            if entry['conflict'] or (not entry['runtime'].connected and not entry.get('suspended')):
                state['threadRuntimeStatus'] = {'type': 'notLoaded'}
                state['supportedOperations'] = []
            if not force and state == entry['snapshot']: return
            revision = self.revisions.get(tid, 0) + 1
            self.bus._write({'type': 'broadcast', 'method': 'thread-stream-state-changed',
                'version': 11, 'sourceClientId': self.bus.client_id,
                'params': {'hostId': 'local', 'conversationId': tid,
                           'change': {'type': 'snapshot', 'revision': revision, 'conversationState': state}}})
            self.revisions[tid] = revision
            entry['snapshot'] = state


    def _reconnect_bus(self):
        with self.lock:
            if self.bus.connected: return True
            for entry in self.entries.values():
                entry['disconnect'] = True
                entry['followers'].clear()
            if time.monotonic() < self.retry_at: return False
            self.retry_at = time.monotonic() + 2
            entries = list(self.entries.items())
        try:
            self._connect_bus()
        except (OSError, IPCError):
            self.bus.close()
            return False
        for tid, entry in entries:
            with self.lock:
                if self.closed.is_set(): return False
                if self.entries.get(tid) is not entry: continue
                runtime = entry['runtime']
                if not runtime.connected: continue
                entry['in_flight'] = entry.get('in_flight', 0) + 1
            try:
                loaded = runtime.rpc('thread/loaded/list', {}).get('data', [])
                foreign = False
                if tid in loaded:
                    try: self.bus.owner(tid, timeout_ms=1500)
                    except IPCError as exc:
                        if str(exc) != 'no-client-found': raise
                    else: foreign = True
                with self.lock:
                    if self.entries.get(tid) is not entry or entry['runtime'] is not runtime: continue
                    if tid not in loaded or foreign: entry['conflict'] = True
                    entry['disconnect'] = False
                    entry['snapshot'] = None
            except (OSError, IPCError):
                with self.lock:
                    if self.entries.get(tid) is entry and entry['runtime'] is runtime:
                        entry['conflict'] = True
                        entry['disconnect'] = False
            finally:
                with self.lock:
                    entry['in_flight'] -= 1
        return self.bus.connected and not self.closed.is_set()

    def _pump(self):
        while not self.closed.is_set():
            self.dirty.wait(.25)
            if self.closed.wait(.075): break
            self.dirty.clear()
            self._release_finished()
            with self.lock:
                if not self.entries: continue
            if not self._reconnect_bus(): continue
            with self.lock:
                for tid in list(self.entries):
                    try: self.publish(tid)
                    except (OSError, IPCError):
                        self.entries[tid]['conflict'] = True

    @staticmethod
    def _assert_releasable(tid, entry):
        if entry.get('in_flight'): raise IPCError('cannot release a session with pending operations')
        state = entry['runtime'].current(tid)
        if entry['runtime'].connected and (not state or state.get('requests') or
                state['threadRuntimeStatus']['type'] != 'idle' or
                any(t['status'] == 'inProgress' for t in state['turns'])):
            raise IPCError('cannot release a running or waiting session')

    def release(self, tid, authorize=lambda: None):
        with self.lock:
            authorize()
            if tid in self.loading: raise IPCError('cannot release a loading session')
            entry = self.entries.get(tid)
            if entry is None: return {'threadId': tid, 'state': 'released'}
            self._assert_releasable(tid, entry)
            # One process per thread prevents releasing another session's runtime.
            entry['conflict'] = True
            try:
                self.publish(tid, force=True)
            except (OSError, IPCError):
                pass  # A lost invalidation must not retain the native writer lock.
            entry['runtime'].close()
            self.entries.pop(tid)
            if not entry['receipts']: self.receipts.pop(tid, None)
            # Closing the owner connection invalidates follower caches. Other owners are
            # kept on this bus, so reconnect is deferred until all entries are released.
            if not self.entries and not self.loading: self.bus.close()
            return {'threadId': tid, 'state': 'released'}

    def close(self):
        self.closed.set()
        self.prewarm.close()
        with self.lock:
            for entry in self.entries.values():
                entry['conflict'] = True
                entry['runtime'].close()
            self.entries.clear()
            self.receipts.clear()
            self.follower_events.clear()
            self.bus.close()
        if self.worker and self.worker is not threading.current_thread(): self.worker.join(2)
