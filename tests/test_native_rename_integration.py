"""Native names in a private home; no real account or model execution from renaming."""
import os
import unittest
from unittest.mock import patch
from carryon.app_server.app_server import AppServer
from carryon.desktop_ipc.ipc import IPCError
from carryon.routes.api import dispatch
from run_appserver_regression import wait_until
from test_native_archives_integration import NativeArchivesIntegration as Fixtures


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeRenameIntegration(unittest.TestCase):
    setUp = Fixtures.setUp
    tearDown = Fixtures.tearDown
    owner_fixture = Fixtures.owner_fixture

    def rename(self, key='rename-once', name='中文名称 🧭'):
        dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/rename', {'requestId': key, 'name': name})
        wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
        return self.journal.get(key)

    def check(self):
        self.assertEqual(self.runtime.rpc('thread/read', {'threadId': self.tid, 'includeTurns': False})['thread']['name'], '中文名称 🧭')
        self.assertEqual(self.requests, self.baseline_requests)

    def test_direct_persists_name_without_new_turn(self):
        job = self.rename(); self.assertEqual(job['state'], 'completed', job); self.check()
        self.assertEqual(self.bridge.catalog.archive_record(self.tid)['name'], '中文名称 🧭')

    def test_unknown_query_confirms_without_replay_and_blocks_different_write(self):
        original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/name/set':
                writes.append(params); raise IPCError('fixture lost reply', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost):
            self.assertEqual(self.rename()['state'], 'uncertain')
            with self.assertRaisesRegex(IPCError, '待核对'): self.rename('other-name', '其他名称')
            self.assertEqual(self.rename()['state'], 'uncertain')
            self.assertEqual(len(writes), 1)
            self.assertEqual(self.bridge.refresh_job('rename-once')['state'], 'completed')
            self.assertEqual(len(writes), 1)
        self.check()

    def test_loaded_owner_name(self):
        self.owner_fixture(False)
        job = self.rename(); self.assertEqual(job['state'], 'completed', job); self.check()

    def test_suspended_owner_name_does_not_load_or_resume(self):
        manager = self.owner_fixture(True)
        job = self.rename(); self.assertEqual(job['state'], 'completed', job)
        self.assertTrue(manager.entries[self.tid]['suspended'])
        wait_until(lambda: self.bridge.ipc.current(self.tid).get('title') == '中文名称 🧭')
        self.assertEqual(self.bridge.history(self.tid)['thread']['title'], '中文名称 🧭')
        self.assertFalse(self.runtime.connected)
        self.assertEqual(self.bridge.catalog.archive_record(self.tid)['name'], '中文名称 🧭')
        self.assertEqual(self.requests, self.baseline_requests)

    def test_suspended_owner_unknown_query_updates_title_without_replay(self):
        manager = self.owner_fixture(True); original = AppServer.rpc
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/name/set': raise IPCError('fixture lost reply', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost): self.assertEqual(self.rename()['state'], 'uncertain')
        self.assertNotEqual(manager.entries[self.tid]['snapshot']['title'], '中文名称 🧭')
        self.assertEqual(self.bridge.refresh_job('rename-once')['state'], 'completed')
        wait_until(lambda: self.bridge.ipc.current(self.tid).get('title') == '中文名称 🧭')
        self.assertEqual(self.bridge.history(self.tid)['thread']['title'], '中文名称 🧭')
        self.assertFalse(self.runtime.connected)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_suspended_owner_stale_generation_or_bad_read_cannot_publish_title(self):
        manager = self.owner_fixture(True); original = AppServer.rpc
        for phase in ('generation', 'identity'):
            before = manager.entries[self.tid]['snapshot']
            def bad(runtime, method, params, *args, **kwargs):
                result = original(runtime, method, params, *args, **kwargs)
                if method == 'thread/read':
                    if phase == 'generation': self.bridge.generation += 1
                    else: result = {**result, 'thread': {**result['thread'], 'id': 'other-thread'}}
                return result
            with patch.object(AppServer, 'rpc', bad): self.assertEqual(self.rename('bad-' + phase)['state'], 'uncertain')
            self.assertIs(manager.entries[self.tid]['snapshot'], before)
            self.assertEqual(self.bridge.refresh_job('bad-' + phase)['state'], 'completed')
        self.assertEqual(self.requests, self.baseline_requests)

    def test_generation_change_after_write_is_unknown(self):
        original = self.runtime.rpc
        def changed(method, params, *args, **kwargs):
            result = original(method, params, *args, **kwargs)
            if method == 'thread/name/set': self.bridge.generation += 1
            return result
        with patch.object(self.runtime, 'rpc', changed): self.assertEqual(self.rename()['state'], 'uncertain')
        self.assertEqual(self.requests, self.baseline_requests)

    def test_same_runtime_session_change_after_write_or_read_is_unknown(self):
        original = self.runtime.rpc
        for phase in ('thread/name/set', 'thread/read'):
            old = self.runtime.session_id
            def changed(method, params, *args, **kwargs):
                result = original(method, params, *args, **kwargs)
                if method == phase: self.runtime.session_id = 'fixture-replacement-session'
                return result
            try:
                with patch.object(self.runtime, 'rpc', changed):
                    self.assertEqual(self.rename('changed-' + phase.replace('/', '-'))['state'], 'uncertain')
            finally: self.runtime.session_id = old
            self.assertEqual(self.bridge.refresh_job('changed-' + phase.replace('/', '-'))['state'], 'completed')
        self.assertEqual(self.requests, self.baseline_requests)
