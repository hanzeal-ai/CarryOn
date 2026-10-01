"""Explicit, removable owner service. Each loaded thread owns one runtime lifetime."""
import threading
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

    def load(self, tid, authorize=lambda: None):
        valid_id(tid)
        with self.lock:
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
            if not self.bus.connected: self.bus.connect()
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
                self.entries[tid] = {'runtime': runtime, 'snapshot': None, 'followers': set(),
                                     'conflict': False, 'receipts': self.receipts.setdefault(tid, OrderedDict()),
                                     'disconnect': False, 'initial_turn_ids': {t['turnId'] for t in state['turns']},
                                     'submitted_turn_ids': set(), 'awaiting_new_turn': False,
                                     'recovery_receipts': OrderedDict()}
                self.publish(tid, force=True)
            except Exception:
                self.entries.pop(tid, None)
                if not self.receipts.get(tid): self.receipts.pop(tid, None)
                runtime.close()
                raise
            if self.worker is None:
                self.worker = threading.Thread(target=self._pump, daemon=True, name='owner-state-publisher')
                self.worker.start()
            return self.describe(tid)

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
            if entry['conflict']: raise IPCError('owner-conflict')
        except Exception:
            runtime.close()
            raise
        entry.update(runtime=runtime, suspended=False, snapshot=None,
            initial_turn_ids={t['turnId'] for t in state['turns']},
            submitted_turn_ids=set(), awaiting_new_turn=False, recovery_receipts=OrderedDict())
        self.publish(tid, force=True)

    def adopt(self, tid, runtime, authorize=lambda: None):
        """Own the still-live creator; empty threads cannot be closed and resumed."""
        valid_id(tid)
        with self.lock:
            authorize()
            if self.closed.is_set(): raise IPCError('owner-service-closed')
            if tid in self.entries: raise IPCError('conversation-already-owned')
            state = runtime.current(tid)
            if (not runtime.connected or not state or
                    state.get('threadMetadata', {}).get('historyMode') != 'paginated' or
                    state['threadRuntimeStatus']['type'] != 'idle' or state.get('requests') or state['turns']):
                raise IPCError('new conversation has no idle paginated baseline')
            if not self.bus.connected: self.bus.connect()
            try: self.bus.owner(tid, timeout_ms=3000)
            except IPCError as exc:
                if str(exc) != 'no-client-found': raise
            else: raise IPCError('owner appeared during creation')
            authorize()
            runtime.on_change = self.dirty.set
            self.entries[tid] = {'runtime': runtime, 'snapshot': None, 'followers': set(),
                'conflict': False, 'receipts': self.receipts.setdefault(tid, OrderedDict()),
                'disconnect': False, 'initial_turn_ids': set(), 'submitted_turn_ids': set(),
                'awaiting_new_turn': False, 'recovery_receipts': OrderedDict()}
            try:
                self.publish(tid, force=True)
            except Exception:
                self.entries.pop(tid)
                if not self.receipts.get(tid): self.receipts.pop(tid, None)
                raise
            if self.worker is None:
                self.worker = threading.Thread(target=self._pump, daemon=True, name='owner-state-publisher')
                self.worker.start()
            return self.describe(tid)

    def can_handle(self, envelope):
        if not isinstance(envelope, dict): return False
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
        with self.lock:
            self._drain_followers()
            if not self.can_handle(envelope): raise IPCError('conversation-not-owned')
            method, params = envelope['method'], envelope.get('params') or {}
            tid = params['conversationId']; entry = self.entries[tid]
            if method == 'thread-owner-discovery': return {'supportsUntrustedAppInput': False}
            if method == 'thread-follower-load-complete-history':
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
            recovery = method in APPROVALS or method == 'thread-follower-interrupt-turn'
            receipts = entry['recovery_receipts'] if recovery else entry['receipts']
            if key in receipts:
                previous = receipts[key]
                if previous['fingerprint'] != fingerprint: raise IPCError('request-id-content-mismatch')
                if previous.get('error'): raise IPCError(previous['error'], uncertain=previous['uncertain'])
                self._submitted(entry, method, previous['result'])
                return deepcopy(previous['result'])
            if recovery:
                # Recovery is runtime-scoped: old replies are also guarded by the
                # native pending request / active turn identity, never replayed blindly.
                if len(receipts) >= 1000: receipts.popitem(last=False)
            elif sum(len(values) for values in self.receipts.values()) >= 1000:
                raise IPCError('owner receipt limit reached; restart service after checking prior requests')
            receipt = {'fingerprint': fingerprint, 'error': 'request outcome unknown; do not resend', 'uncertain': True}
            receipts[key] = receipt
            try:
                if entry.get('suspended'): self._resume(tid)
                result = forward(entry['runtime'], tid, method, params)
                receipt.update(result=deepcopy(result), error=None, uncertain=False)
                self._submitted(entry, method, result)
                self.dirty.set()
                return result
            except Exception as exc:
                receipt.update(error=str(exc), uncertain=isinstance(exc, IPCError) and exc.uncertain)
                if receipt['uncertain'] and method in ('thread-follower-start-turn', 'thread-follower-compact-thread'):
                    entry['awaiting_new_turn'] = True
                raise

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

    def _pump(self):
        while not self.closed.is_set():
            self.dirty.wait(.25)
            if self.closed.wait(.075): break
            self.dirty.clear()
            with self.lock:
                self._release_finished()
                if not self.entries: continue
                if not self.bus.connected:
                    for entry in self.entries.values():
                        entry['disconnect'] = True
                        entry['followers'].clear()
                    if time.monotonic() < self.retry_at: continue
                    self.retry_at = time.monotonic() + 2
                    try:
                        self.bus.connect()
                        for tid, entry in self.entries.items():
                            if not entry['runtime'].connected: continue
                            loaded = entry['runtime'].rpc('thread/loaded/list', {}).get('data', [])
                            if tid not in loaded:
                                entry['conflict'] = True
                                continue
                            try: self.bus.owner(tid, timeout_ms=1500)
                            except IPCError as exc:
                                if str(exc) != 'no-client-found': raise
                            else: entry['conflict'] = True
                            entry['disconnect'] = False
                            entry['snapshot'] = None
                    except (OSError, IPCError):
                        self.bus.close()
                        continue
                for tid in list(self.entries):
                    try: self.publish(tid)
                    except (OSError, IPCError):
                        self.entries[tid]['conflict'] = True

    @staticmethod
    def _assert_releasable(tid, entry):
        state = entry['runtime'].current(tid)
        if entry['runtime'].connected and (not state or state.get('requests') or
                state['threadRuntimeStatus']['type'] != 'idle' or
                any(t['status'] == 'inProgress' for t in state['turns'])):
            raise IPCError('cannot release a running or waiting session')

    def release(self, tid, authorize=lambda: None):
        with self.lock:
            authorize()
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
            if not self.entries: self.bus.close()
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
