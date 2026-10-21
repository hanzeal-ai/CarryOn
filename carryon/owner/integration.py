"""Composition root for desktop workspace session ownership."""
import time
import threading
from contextlib import contextmanager
from carryon.sessions.bridge import Bridge
from carryon.sessions.catalog import valid_id
from carryon.contracts import digest, validate_request_id
from carryon.errors import IPCError
from carryon.desktop_ipc.ipc import DesktopIPC
from carryon.errors import BridgeError
from carryon.owner.manager import OwnerManager


class OwnerBridge(Bridge):
    def __init__(self, socket_path, catalog, journal, *, owner_directory, **kwargs):
        super().__init__(socket_path, catalog, journal, ipc_factory=kwargs.pop('ipc_factory', DesktopIPC), **kwargs)
        self.owner_directory = owner_directory
        self.owner_service = None
        self.compose_workers = set()

    def enable(self):
        result = super().enable()
        self.owners()
        return result

    def status(self):
        from carryon.sessions.creation_settings import supported
        return {**super().status(), 'supportsPluginManagement': True, 'supportsThreadSections': True, 'supportsFullTextSearch': True, 'supportsArchiving': True, 'supportsSessionLoading': True, 'supportsProjectlessCreation': True, 'supportsCreationReferences': True, 'supportedCreationSettings': supported()}

    def owners(self):
        with self.lock:
            self.require()
            if self.owner_service is None:
                self.owner_service = OwnerManager(self.catalog.home, self.owner_directory, self.catalog)
            return self.owner_service

    def queue(self, thread_id, parent_id=None, *, authoritative=False):
        from carryon.sessions.queue import projection
        service = self.owner_service
        if service is not None and parent_id is None:
            with service.lock:
                entry = service.entries.get(thread_id)
                runtime = entry['runtime'] if entry and not entry.get('suspended') and not entry['conflict'] else None
            if runtime is not None:
                self.assert_target(thread_id)
                ipc, generation = self.require()
                result = projection(runtime.queue_snapshot(thread_id, refresh=authoritative), 'app-server')
                with self.lock: self.check_generation(ipc, generation)
                service.dirty.set()
                return result
        return super().queue(thread_id, parent_id, authoritative=authoritative)

    @contextmanager
    def native_session(self, tid, authorize, *, loaded_only=False, submitted_turns=None, track_future_turns=False):
        """Keep an owned runtime alive and serialize native transactions with IPC turns."""
        service = self.owner_service
        if service is None:
            yield None
            return
        with service.lock:
            owned = tid in service.entries
        if not owned:
            yield None
            return
        with service._thread_lock(tid):
            if loaded_only:
                with service.lock:
                    entry = service.entries.get(tid)
                    if not entry or entry.get('suspended'):
                        raise IPCError('此操作需要已加载的原生会话')
            service.load(tid, authorize)
            with service.lock:
                entry = service.entries[tid]
                runtime = entry['runtime']
                entry['in_flight'] = entry.get('in_flight', 0) + 1
                prior_turn_ids = {turn['turnId'] for turn in runtime.current(tid)['turns']}
            attempted, track_outcome = False, False
            def guarded(write):
                nonlocal attempted
                with service.lock:
                    if (service.closed.is_set() or service.entries.get(tid) is not entry
                            or entry['runtime'] is not runtime or entry['conflict'] or entry['disconnect']
                            or not service.bus.connected or not runtime.connected):
                        raise IPCError('原生操作期间会话归属已改变')
                    attempted = True
                    write()
            try:
                yield runtime, guarded
                track_outcome = True
            except Exception as exc:
                track_outcome = (exc.uncertain if isinstance(exc, IPCError) else not isinstance(exc, BridgeError))
                raise
            finally:
                with service.lock:
                    if track_future_turns and attempted and track_outcome:
                        entry['awaiting_new_turn'] = True
                    current = runtime.current(tid)
                    if current is not None:
                        entry['submitted_turn_ids'].update(submitted_turns if submitted_turns is not None else
                            (turn['turnId'] for turn in current['turns'] if turn['turnId'] not in prior_turn_ids))
                    entry['in_flight'] -= 1
                service.dirty.set()

    def prepare_compose(self, thread_id, request_id, fingerprint, source, authorize, run):
        # Persist identity before slow discovery/resume, so the cloud can return
        # promptly and both HTTP and live updates can track the same request.
        with self.lock:
            self.require()
            if authorize: authorize()
            previous = self.journal.get(request_id)
            if previous:
                if previous.get('composeFingerprint') != fingerprint:
                    raise BridgeError('requestId 已用于不同内容')
                return previous
            if any(j['threadId'] == thread_id and j['state'] in ('preparing', 'dispatching')
                   for j in self.journal.list()):
                raise BridgeError('会话正在提交操作，请稍后重试')
            job = {'id': request_id, 'threadId': thread_id, 'kind': 'compose',
                   'state': 'preparing', 'created': time.time(), 'fingerprint': fingerprint,
                   **(source or {}), 'composeFingerprint': fingerprint}
            self.journal.insert(job)
        def execute():
            try: run(job)
            except Exception as exc:
                # No turn was sent by compose's preparation. Dispatch owns any
                # subsequent accepted/failed/uncertain receipt itself.
                self.journal.update(request_id, expected=job, state='failed', error=str(exc))
            finally:
                with self.lock: self.compose_workers.discard(threading.current_thread())
        worker = None
        with self.lock:
            try:
                self.require()
                worker = threading.Thread(target=execute, daemon=True, name='owner-compose')
                self.compose_workers.add(worker)
                worker.start()
            except Exception as exc:
                if worker is not None: self.compose_workers.discard(worker)
                return self.journal.update(request_id, expected=job, state='failed', error=str(exc))
        return self.journal.get(request_id)

    def send_snapshot(self, ipc, generation, thread_id, authorize=None, parent_id=None):
        try:
            return ipc.snapshot(thread_id)
        except IPCError as exc:
            # Only a definite missing owner permits resume; never replay a write
            # or recover an ephemeral side conversation from persisted history.
            if str(exc) != 'no-client-found' or exc.uncertain or parent_id is not None:
                raise

        def check():
            with self.lock:
                self.check_generation(ipc, generation)
                self.assert_target(thread_id)
                if authorize: authorize()

        check()
        service = self.owners()
        service.load(thread_id, check)
        check()
        self.notify()
        return ipc.snapshot(thread_id)

    def session_control(self, tid, data, source=None, authorize=None):
        valid_id(tid); validate_request_id(data.get('requestId'))
        action = data.get('action')
        if action not in ('load', 'release'): raise ValueError('无效会话加载操作')
        ipc, generation = self.require()
        self.assert_target(tid)
        key = data['requestId']; fingerprint = digest([tid, action])
        def check():
            self.check_generation(ipc, generation)
            self.assert_target(tid)
            if authorize: authorize()
        # Load/release are synchronous: a repeated request reads its receipt, never sends twice.
        with self.lock:
            check()
            previous = self.journal.get(key)
            if previous:
                if previous.get('fingerprint') != fingerprint: raise BridgeError('requestId 已用于不同内容')
                return previous
            self.journal.insert({'id': key, 'threadId': tid, 'kind': 'session:'+action,
                'fingerprint': fingerprint, 'state': 'preparing', 'created': time.time(), **(source or {})})
            service = self.owners()
        try:
            result = service.load(tid, check) if action == 'load' else service.release(tid, check)
            job = self.journal.update(key, state='completed', result=result, evidence='owner-service')
            self.notify()
            return job
        except Exception as exc:
            return self.journal.update(key, state='uncertain' if isinstance(exc, IPCError) and exc.uncertain else 'failed', error=str(exc))

    def reconnect(self):
        # A desktop IPC reconnect must not terminate independently running owner tasks.
        Bridge.disable(self)
        return self.enable()

    def shutdown(self):
        # Process shutdown ends owned runtimes; ordinary bridge off only closes remote control.
        result = super().disable()
        service, self.owner_service = self.owner_service, None
        if service: service.close()
        with self.lock: workers = list(self.compose_workers)
        for worker in workers: worker.join()
        return result
