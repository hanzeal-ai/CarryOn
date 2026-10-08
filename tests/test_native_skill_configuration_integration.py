"""Persisted skill enablement against the installed native server in a private home."""
import os
import unittest
from unittest.mock import patch
from carryon.app_server.app_server import AppServer
from carryon.desktop_ipc.ipc import IPCError
from carryon.routes.api import dispatch
import test_native_archives_integration as fixtures
from run_appserver_regression import wait_until

@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeSkillConfigurationIntegration(unittest.TestCase):
    setUp = fixtures.NativeArchivesIntegration.setUp
    tearDown = fixtures.NativeArchivesIntegration.tearDown
    def prepare_skill(self):
        directory = self.root / 'home' / 'skills' / 'fixture'
        directory.mkdir(parents=True)
        self.path = str((directory / 'SKILL.md').resolve())
        (directory / 'SKILL.md').write_text('---\nname: fixture\ndescription: Private fixture skill\n---\nLocal fixture only.\n')
        return '/api/threads/' + self.tid + '/skills/config'
    def send_config(self, route, key, enabled):
        dispatch(self.bridge, 'POST', route, {'requestId': key, 'path': self.path, 'enabled': enabled})
        wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
        return self.journal.get(key)
    def test_disable_enable_and_exact_receipt_without_model_calls(self):
        route = self.prepare_skill()
        for key, enabled in [('disable-fixture', False), ('enable-fixture', True)]:
            job = self.send_config(route, key, enabled)
            self.assertEqual(job['state'], 'completed', job)
            self.assertEqual(job['result'], {'threadId': self.tid, 'path': self.path, 'enabled': enabled})
            page = self.runtime.rpc('skills/list', {'cwds': [self.bridge.catalog.archive_record(self.tid)['cwd']], 'forceReload': True})
            matches = [r for r in page['data'][0]['skills'] if r['path'] == self.path]
            self.assertEqual(matches[0]['enabled'], enabled)
        self.assertEqual(self.requests, self.baseline_requests)
    def test_unknown_only_reads_and_blocks_another_configuration(self):
        route = self.prepare_skill(); original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'skills/config/write': writes.append(params); raise IPCError('lost fixture config reply', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost):
            self.assertEqual(self.send_config(route, 'unknown-config', False)['state'], 'uncertain')
            dispatch(self.bridge, 'POST', route, {'requestId': 'unknown-config', 'path': self.path, 'enabled': False})
            with self.assertRaises(IPCError): dispatch(self.bridge, 'POST', route, {'requestId': 'other-config', 'path': self.path, 'enabled': True})
            self.assertEqual(len(writes), 1)
            self.assertEqual(self.bridge.refresh_job('unknown-config')['state'], 'completed')
            self.assertEqual(len(writes), 1)
        self.assertEqual(self.requests, self.baseline_requests)
    def test_unlisted_path_and_revocation_do_not_write(self):
        route = self.prepare_skill(); self.path = str(self.root / 'not-discovered' / 'SKILL.md')
        with patch.object(self.runtime, 'rpc', wraps=self.runtime.rpc) as rpc:
            self.assertEqual(self.send_config(route, 'unknown-path', False)['state'], 'failed')
            self.assertFalse(any(call.args[0] == 'skills/config/write' for call in rpc.call_args_list))
        from carryon.errors import BridgeError
        def denied(): raise BridgeError('fixture revoked', 403)
        with self.assertRaises(BridgeError): dispatch(self.bridge, 'POST', route, {'requestId': 'denied-config', 'path': self.path, 'enabled': False}, authorize=denied)
        self.assertIsNone(self.journal.get('denied-config'))
    def test_suspended_owner_configuration_never_resumes_thread(self):
        route = self.prepare_skill(); manager = fixtures.NativeArchivesIntegration.owner_fixture(self, True)
        original_runtime = manager.entries[self.tid]['runtime']; original_snapshot = manager.entries[self.tid]['snapshot']
        self.assertEqual(self.send_config(route, 'owner-disable', False)['state'], 'completed')
        self.assertIs(manager.entries[self.tid]['runtime'], original_runtime)
        self.assertIs(manager.entries[self.tid]['snapshot'], original_snapshot)
        self.assertTrue(manager.entries[self.tid]['suspended']); self.assertFalse(original_runtime.connected)
        self.assertEqual(self.requests, self.baseline_requests)
    def test_remote_configuration_edit_permission_and_receipt_isolation(self):
        from carryon.routes.remote_scope import scoped_dispatch
        from carryon.workspaces.workspace_access import required_capabilities
        route = self.prepare_skill(); body = {'requestId': 'remote-config', 'path': self.path, 'enabled': False}
        self.assertEqual(required_capabilities('GET', route), ('view',))
        self.assertEqual(required_capabilities('POST', route, body), ('edit',))
        _, job = scoped_dispatch(self.bridge, 'POST', route, body, True, 'binding-one')
        wait_until(lambda: self.journal.list()[0]['state'] not in ('preparing', 'dispatching'))
        _, receipt = scoped_dispatch(self.bridge, 'GET', '/api/jobs/remote-config', None, True, 'binding-one')
        self.assertEqual(job['id'], body['requestId']); self.assertEqual(receipt['state'], 'completed')
        with self.assertRaises(Exception): scoped_dispatch(self.bridge, 'GET', '/api/jobs/remote-config', None, True, 'binding-two')
        with self.assertRaises(Exception): scoped_dispatch(self.bridge, 'POST', route, body, False, 'binding-one')
    def test_unknown_skill_configuration_and_archive_interlock_in_both_orders(self):
        route = self.prepare_skill(); original = AppServer.rpc
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'skills/config/write': raise IPCError('fixture lost config response', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost):
            self.assertEqual(self.send_config(route, 'unknown-before-archive', False)['state'], 'uncertain')
        with self.assertRaises(IPCError): dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/archive', {'requestId': 'blocked-archive'})
        self.assertEqual(self.bridge.refresh_job('unknown-before-archive')['state'], 'completed')
        self.journal.insert({'id': 'pending-archive', 'kind': 'archive', 'threadId': self.tid, 'state': 'uncertain', 'fingerprint': 'fixture', 'created': 1})
        with self.assertRaises(IPCError): dispatch(self.bridge, 'POST', route, {'requestId': 'blocked-config', 'path': self.path, 'enabled': True})
        self.assertIsNone(self.journal.get('blocked-config')); self.assertFalse(self.bridge.catalog.archive_record(self.tid)['archived'])
