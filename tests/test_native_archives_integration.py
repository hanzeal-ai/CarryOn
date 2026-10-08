"""Installed native archival, private home and localhost model; never real task data."""
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from carryon.app_server.app_server import AppServer
from carryon.app_server.app_server_bridge import AppServerBridge
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError
from carryon.routes.api import dispatch
from carryon.store import Journal
from run_appserver_regression import Model, wait_until


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeArchivesIntegration(unittest.TestCase):
    def setUp(self):
        self.requests = []
        outer = self
        class Counter(Model):
            def do_POST(self):
                outer.requests.append(self.path); super().do_POST()
        self.model = ThreadingHTTPServer(('127.0.0.1', 0), Counter)
        threading.Thread(target=self.model.serve_forever, daemon=True).start()
        self.temp = tempfile.TemporaryDirectory(prefix='carryon-native-archives-')
        self.root = Path(self.temp.name); home = self.root / 'home'; home.mkdir()
        (home / 'auth.json').write_text('{"OPENAI_API_KEY":"fixture-not-real"}')
        (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\ncli_auth_credentials_store="file"\n[model_providers.fixture]\nname="Fixture"\nbase_url="http://127.0.0.1:' + str(self.model.server_port) + '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
        self.journal = Journal(self.root / 'journal.sqlite')
        self.bridge = AppServerBridge(home, self.journal); self.bridge.enable()
        self.runtime = self.bridge.ipc
        self.tid = self.runtime.create_thread({'cwd': str(self.root), 'historyMode': 'paginated'}, lambda write: write())['id']
        self.runtime.start_turn(self.tid, {'threadId': self.tid, 'input': [{'type': 'text', 'text': 'local fixture only', 'text_elements': []}]})
        wait_until(lambda: self.runtime.current(self.tid)['turns'] and self.runtime.current(self.tid)['turns'][-1]['status'] == 'completed')
        wait_until(lambda: bool(self.bridge.catalog.list()))
        self.baseline_requests = list(self.requests)
    def tearDown(self):
        self.bridge.disable(); self.journal.conn.close(); self.model.shutdown(); self.model.server_close(); self.temp.cleanup()
    def send(self, action, key):
        dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/' + action, {'requestId': key})
        wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
        return self.journal.get(key)
    def test_paused_goal_round_trip_stays_unloaded_and_does_not_execute(self):
        self.runtime.rpc('thread/goal/set', {'threadId': self.tid, 'objective': 'fixture paused goal', 'status': 'paused'})
        self.assertEqual(self.send('archive', 'archive-once')['state'], 'completed')
        self.assertIsNone(self.runtime.current(self.tid))
        _, page = dispatch(self.bridge, 'GET', '/api/archived')
        self.assertEqual([row['id'] for row in page['threads']], [self.tid])
        self.assertTrue(page['supportsRestore'])
        self.assertEqual(self.send('unarchive', 'restore-once')['state'], 'completed')
        self.assertFalse(self.bridge.catalog.archive_record(self.tid)['archived'])
        self.assertEqual(self.runtime.rpc('thread/read', {'threadId': self.tid, 'includeTurns': False})['thread']['status']['type'], 'notLoaded')
        self.assertEqual(self.runtime.rpc('thread/goal/get', {'threadId': self.tid})['goal']['status'], 'paused')
        self.assertEqual(self.requests, self.baseline_requests)
    def test_unknown_archive_and_restore_query_without_replay(self):
        original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            response = original(runtime, method, params, *args, **kwargs)
            if method in ('thread/archive', 'thread/unarchive'):
                writes.append(method); raise IPCError('fixture lost response', uncertain=True)
            return response
        with patch.object(AppServer, 'rpc', lost):
            self.assertEqual(self.send('archive', 'archive-unknown')['state'], 'uncertain')
            dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/archive', {'requestId': 'archive-unknown'})
            self.assertEqual(writes, ['thread/archive'])
            self.assertEqual(self.bridge.refresh_job('archive-unknown')['state'], 'completed')
            self.assertEqual(self.send('unarchive', 'restore-unknown')['state'], 'uncertain')
            self.assertEqual(self.bridge.refresh_job('restore-unknown')['state'], 'completed')
            self.assertEqual(writes, ['thread/archive', 'thread/unarchive'])
        self.assertEqual(self.requests, self.baseline_requests)
    def test_nonempty_queue_refuses_without_native_archive(self):
        self.runtime.rpc('thread/goal/set', {'threadId': self.tid, 'objective': 'fixture paused', 'status': 'paused'})
        with patch.object(self.runtime, 'queue_snapshot', return_value=[{'id': 'pending'}]), patch.object(self.runtime, 'queue_busy', return_value=True):
            self.assertEqual(self.send('archive', 'queue-refused')['state'], 'failed')
        self.assertFalse(self.bridge.catalog.archive_record(self.tid)['archived'])
        self.assertEqual(self.requests, self.baseline_requests)

    def owner_fixture(self, suspended):
        from carryon.owner.manager import OwnerManager
        from carryon.owner.integration import OwnerBridge
        from carryon.sessions.catalog import Catalog
        self.bridge.disable()
        follower = DesktopIPC('unused'); follower.client_id = 'fixture-follower'
        class Transport(DesktopIPC):
            def connect(self):
                self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                for ipc in (self, follower):
                    threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
            def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
        catalog = Catalog(self.root / 'home')
        manager = OwnerManager(catalog.home, self.root / 'owner', catalog, transport_factory=Transport)
        self.bridge = OwnerBridge('unused', catalog, self.journal, owner_directory=self.root / 'owner')
        self.bridge.ipc = follower; self.bridge.enabled = True; self.bridge.owner_service = manager
        manager.load(self.tid); self.runtime = manager.entries[self.tid]['runtime']
        follower.snapshot(self.tid)
        if suspended:
            with manager._thread_lock(self.tid), manager.lock:
                manager.publish(self.tid, force=True)
                manager.entries[self.tid]['suspended'] = True
                self.runtime.close()
        return manager

    def test_loaded_owner_archive_keeps_writer_until_native_write(self):
        self.owner_round_trip(False)

    def test_suspended_owner_archive_does_not_resume_task(self):
        self.owner_round_trip(True)

    def owner_round_trip(self, suspended):
        manager = self.owner_fixture(suspended)
        # Socketpair has no coordinator; keep the fixture follower link alive.
        with patch.object(manager.bus, 'close', lambda: None):
            archived = self.send('archive', 'owner-archive')
            self.assertEqual(archived['state'], 'completed', archived)
            self.assertNotIn(self.tid, manager.entries)
            self.assertFalse(self.runtime.connected)
            self.assertEqual(self.send('unarchive', 'owner-restore')['state'], 'completed')
            self.assertNotIn(self.tid, manager.entries)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_late_reply_after_generation_change_cannot_clear_new_scope(self):
        original = self.runtime.rpc
        def changed(method, params, *args, **kwargs):
            result = original(method, params, *args, **kwargs)
            if method == 'thread/archive': self.bridge.generation += 1
            return result
        with patch.object(self.runtime, 'rpc', changed):
            job = self.send('archive', 'late-reply')
        self.assertEqual(job['state'], 'uncertain', job)
        self.assertIsNotNone(self.runtime.current(self.tid))

    def test_owner_replacement_is_not_closed_by_old_archive_reply(self):
        manager = self.owner_fixture(False); original = self.runtime.rpc
        replacement = AppServer(self.root / 'home', runtime_directory=self.root / 'replacement'); replacement.connect()
        old_runtime = self.runtime
        def replaced(method, params, *args, **kwargs):
            result = original(method, params, *args, **kwargs)
            if method == 'thread/archive': manager.entries[self.tid]['runtime'] = replacement
            return result
        try:
            with patch.object(old_runtime, 'rpc', replaced), patch.object(manager.bus, 'close', lambda: None):
                job = self.send('archive', 'owner-replaced')
                self.assertEqual(job['state'], 'uncertain', job)
                self.assertIs(manager.entries[self.tid]['runtime'], replacement)
                self.assertTrue(replacement.connected)
                with self.assertRaises(IPCError): self.bridge.refresh_job('owner-replaced')
                self.assertTrue(replacement.connected)
        finally: old_runtime.close()

    def test_recovery_waits_for_owner_transaction_before_bridge_lock(self):
        manager = self.owner_fixture(False); original = self.runtime.rpc
        def lost(method, params, *args, **kwargs):
            result = original(method, params, *args, **kwargs)
            if method == 'thread/archive': raise IPCError('lost', uncertain=True)
            return result
        with patch.object(self.runtime, 'rpc', lost):
            self.assertEqual(self.send('archive', 'owner-unknown')['state'], 'uncertain')
        thread_lock = manager._thread_lock(self.tid)
        held = threading.Event(); waiting = threading.Event(); acquired = threading.Event(); errors = []
        class TimedLock:
            def __enter__(self):
                waiting.set()
                if not thread_lock.acquire(timeout=2): raise IPCError('fixture deadlock detected')
            def __exit__(self, *_): thread_lock.release()
        def existing_operation():
            with thread_lock:
                held.set(); waiting.wait(3)
                with self.bridge.lock: acquired.set()
        def query():
            try: self.bridge.refresh_job('owner-unknown')
            except Exception as error: errors.append(str(error))
        first = threading.Thread(target=existing_operation, daemon=True); first.start(); self.assertTrue(held.wait(3))
        with patch.object(manager, '_thread_lock', lambda _: TimedLock()), patch.object(manager.bus, 'close', lambda: None):
            second = threading.Thread(target=query, daemon=True); second.start(); second.join(4); first.join(4)
        self.assertFalse(second.is_alive()); self.assertFalse(first.is_alive()); self.assertTrue(acquired.is_set()); self.assertEqual(errors, [])
        self.assertEqual(self.journal.get('owner-unknown')['state'], 'completed')
