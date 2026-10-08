"""Installed native plugin control in an isolated home and local marketplace."""
import json
import os
import unittest
from unittest.mock import patch
import test_native_archives_integration as fixtures
from carryon.app_server.app_server import AppServer
from carryon.desktop_ipc.ipc import IPCError
from carryon.routes.api import dispatch
from run_appserver_regression import wait_until

@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativePluginsIntegration(unittest.TestCase):
    setUp = fixtures.NativeArchivesIntegration.setUp
    tearDown = fixtures.NativeArchivesIntegration.tearDown
    def prepare(self):
        root = self.root.resolve(); market = root / '.agents/plugins/marketplace.json'; market.parent.mkdir(parents=True)
        market.write_text(json.dumps({'name': 'carryon-fixture', 'plugins': [{'name': 'fixture', 'source': {'source': 'local', 'path': './fixture'}}]}))
        manifest = root / 'fixture/.codex-plugin/plugin.json'; manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'name': 'fixture', 'version': '1.0.0', 'description': 'Private fixture'}))
        self.pid = 'fixture@carryon-fixture'; self.route = '/api/threads/' + self.tid + '/plugins'
    def send(self, action, key):
        dispatch(self.bridge, 'POST', self.route, {'requestId': key, 'action': action, 'pluginId': self.pid})
        wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
        return self.journal.get(key)
    def test_inventory_detail_install_uninstall_and_authorization_remain_distinct(self):
        self.prepare(); _, page = dispatch(self.bridge, 'GET', self.route)
        plugin = next(p for p in page['plugins'] if p['id'] == self.pid); self.assertFalse(plugin['installed'])
        _, detail = dispatch(self.bridge, 'GET', self.route + '?pluginId=' + self.pid)
        self.assertEqual(detail['plugin']['summary']['id'], self.pid); self.assertEqual(detail['plugin']['description'], 'Private fixture')
        for action in ['install', 'uninstall']:
            job = self.send(action, 'plugin-' + action); self.assertEqual(job['state'], 'completed', job)
            self.assertEqual(job['result']['installed'], action == 'install'); self.assertEqual(job['result']['pluginId'], self.pid)
            if action == 'install': self.assertEqual(job['result']['appsNeedingAuth'], [])
        self.assertEqual(self.requests, self.baseline_requests)
    def test_lost_install_receipt_reads_canonical_state_without_replay_or_fake_auth(self):
        self.prepare(); original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'plugin/install': writes.append(params); raise IPCError('fixture lost install reply', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost):
            self.assertEqual(self.send('install', 'unknown-plugin')['state'], 'uncertain')
            dispatch(self.bridge, 'POST', self.route, {'requestId': 'unknown-plugin', 'action': 'install', 'pluginId': self.pid})
            with self.assertRaises(IPCError): self.send('uninstall', 'blocked-uninstall')
            job = self.bridge.refresh_job('unknown-plugin'); self.assertEqual(job['state'], 'completed'); self.assertIsNone(job['result']['appsNeedingAuth'])
            self.assertEqual(len(writes), 1); self.assertEqual(writes[0]['installAttemptId'], 'unknown-plugin')
        self.assertEqual(self.requests, self.baseline_requests)
    def test_foreign_plugin_does_not_install(self):
        self.prepare(); self.pid = 'foreign-plugin'
        with patch.object(self.runtime, 'rpc', wraps=self.runtime.rpc) as rpc:
            self.assertEqual(self.send('install', 'foreign-refused')['state'], 'failed')
            self.assertFalse(any(c.args[0] == 'plugin/install' for c in rpc.call_args_list))
    def test_suspended_owner_plugin_changes_never_resume_task(self):
        self.prepare(); manager = fixtures.NativeArchivesIntegration.owner_fixture(self, True)
        original = manager.entries[self.tid]['runtime']; snapshot = manager.entries[self.tid]['snapshot']
        self.assertEqual(self.send('install', 'owner-install')['state'], 'completed')
        self.assertEqual(self.send('uninstall', 'owner-uninstall')['state'], 'completed')
        self.assertIs(manager.entries[self.tid]['runtime'], original); self.assertIs(manager.entries[self.tid]['snapshot'], snapshot)
        self.assertTrue(manager.entries[self.tid]['suspended']); self.assertFalse(original.connected)
        self.assertEqual(self.requests, self.baseline_requests)
    def test_configuration_and_archive_mutual_pending_guards(self):
        self.prepare(); body = {'requestId': 'blocked-config', 'path': '/skills/fixture/SKILL.md', 'enabled': False}
        self.journal.insert({'id': 'unknown-plugin', 'kind': 'plugin-install', 'threadId': self.tid, 'state': 'uncertain', 'fingerprint': 'fixture', 'created': 1})
        with self.assertRaises(IPCError): dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/skills/config', body)
        with self.assertRaises(IPCError): dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/archive', {'requestId': 'blocked-archive'})
        self.journal.update('unknown-plugin', state='acknowledged')
        self.journal.insert({'id': 'unknown-skill', 'kind': 'skill-config', 'threadId': self.tid, 'state': 'uncertain', 'fingerprint': 'fixture', 'created': 1})
        with self.assertRaises(IPCError): self.send('install', 'blocked-by-skill')
        self.journal.update('unknown-skill', state='acknowledged')
        self.journal.insert({'id': 'unknown-archive', 'kind': 'archive', 'threadId': self.tid, 'state': 'uncertain', 'fingerprint': 'fixture', 'created': 1})
        with self.assertRaises(IPCError): self.send('install', 'blocked-by-archive')
        for key in ['blocked-config', 'blocked-archive', 'blocked-by-skill', 'blocked-by-archive']: self.assertIsNone(self.journal.get(key))
    def test_generation_loss_after_native_write_keeps_unknown_receipt(self):
        self.prepare(); original = AppServer.rpc; writes = []
        def changed(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'plugin/install':
                writes.append(params)
                with self.bridge.lock: self.bridge.generation += 1
            return result
        with patch.object(AppServer, 'rpc', changed):
            job = self.send('install', 'generation-plugin'); self.assertEqual(job['state'], 'uncertain', job)
        self.assertEqual(len(writes), 1)
        self.assertEqual(self.requests, self.baseline_requests)
    def test_authorization_loss_after_native_write_keeps_unknown_receipt(self):
        self.prepare(); original = AppServer.rpc; allowed = [True]
        from carryon.errors import BridgeError
        def authorize():
            if not allowed[0]: raise BridgeError('fixture revoked', 403)
        def changed(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'plugin/install': allowed[0] = False
            return result
        with patch.object(AppServer, 'rpc', changed):
            dispatch(self.bridge, 'POST', self.route, {'requestId': 'revoked-plugin', 'action': 'install', 'pluginId': self.pid}, authorize=authorize)
            wait_until(lambda: self.journal.get('revoked-plugin')['state'] not in ('preparing', 'dispatching'))
            self.assertEqual(self.journal.get('revoked-plugin')['state'], 'uncertain')
        self.assertEqual(self.requests, self.baseline_requests)
    def test_native_search_scopes_and_discovery_install_without_default_inventory(self):
        from urllib.parse import urlencode
        self.prepare(); context = {'searchTerm': 'fixture', 'scope': 'personal', 'cursor': None}
        original = AppServer.rpc
        def inventory_hidden(runtime, method, params, *args, **kwargs):
            if method == 'plugin/list': return {'marketplaces': [], 'marketplaceLoadErrors': []}
            return original(runtime, method, params, *args, **kwargs)
        with patch.object(AppServer, 'rpc', inventory_hidden):
            for scope in ('global', 'workspace', 'personal'):
                _, page = dispatch(self.bridge, 'GET', self.route + '?' + urlencode({'search': 'fixture', 'scope': scope}))
                self.assertIsNone(page['nextCursor'])
                if scope == 'personal':
                    plugin = next(p for p in page['plugins'] if p['id'] == self.pid); self.assertEqual(plugin['discovery'], context)
            _, page = dispatch(self.bridge, 'GET', self.route + '?' + urlencode({'search': 'fixture', 'scope': 'personal', 'pluginId': self.pid}))
            self.assertEqual(page['plugin']['discovery'], context)
            for action in ('install', 'uninstall'):
                key = 'discovery-' + action
                dispatch(self.bridge, 'POST', self.route, {'requestId': key, 'action': action, 'pluginId': self.pid, 'discovery': context})
                wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
                job = self.journal.get(key); self.assertEqual(job['state'], 'completed', job)
                self.assertEqual(job['body']['discovery'], context); self.assertEqual(job['result']['installed'], action == 'install')
        self.assertEqual(self.requests, self.baseline_requests)
    def test_discovery_identity_mismatch_and_missing_hit_never_write(self):
        self.prepare(); original = AppServer.rpc; writes = []
        def changed(runtime, method, params, *args, **kwargs):
            response = original(runtime, method, params, *args, **kwargs)
            if method == 'plugin/read': response['plugin']['summary']['source'] = {'type': 'local', 'path': '/different-source'}
            if method == 'plugin/install': writes.append(params)
            return response
        with patch.object(AppServer, 'rpc', changed):
            for name, term in [('mismatch', 'fixture'), ('missing', 'absent-fixture')]:
                key = 'search-' + name
                dispatch(self.bridge, 'POST', self.route, {'requestId': key, 'action': 'install', 'pluginId': self.pid, 'discovery': {'searchTerm': term, 'scope': 'personal', 'cursor': None}})
                wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
                self.assertEqual(self.journal.get(key)['state'], 'failed')
        self.assertEqual(writes, []); self.assertEqual(self.requests, self.baseline_requests)
    def test_discovery_lost_reply_recovers_original_source_without_search_or_replay(self):
        self.prepare(); original = AppServer.rpc; writes = []; search_after_write = []
        body = {'requestId': 'search-lost', 'action': 'install', 'pluginId': self.pid, 'discovery': {'searchTerm': 'fixture', 'scope': 'personal', 'cursor': None}}
        def lost(runtime, method, params, *args, **kwargs):
            if method == 'plugin/search' and writes: search_after_write.append(params); raise IPCError('fixture search unavailable')
            response = original(runtime, method, params, *args, **kwargs)
            if method == 'plugin/install': writes.append(params); raise IPCError('fixture lost discovery install reply', uncertain=True)
            return response
        with patch.object(AppServer, 'rpc', lost):
            dispatch(self.bridge, 'POST', self.route, body)
            wait_until(lambda: self.journal.get('search-lost')['state'] not in ('preparing', 'dispatching'))
            self.assertEqual(self.journal.get('search-lost')['state'], 'uncertain')
            job = self.bridge.refresh_job('search-lost'); self.assertEqual(job['state'], 'completed', job)
            self.assertEqual(job['body']['discovery'], body['discovery']); self.assertIsNone(job['result']['appsNeedingAuth'])
            self.assertEqual(len(writes), 1); self.assertEqual(search_after_write, [])
        self.assertEqual(self.requests, self.baseline_requests)
    def test_personal_native_search_can_return_more_than_requested_limit(self):
        self.prepare(); market = self.root / '.agents/plugins/marketplace.json'; data = json.loads(market.read_text())
        for n in range(35):
            name = f'fixture-{n:02d}'; data['plugins'].append({'name': name, 'source': {'source': 'local', 'path': './' + name}})
            manifest = self.root / name / '.codex-plugin/plugin.json'; manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'name': name, 'version': '1.0.0', 'description': 'Private paging fixture'}))
        market.write_text(json.dumps(data))
        _, page = dispatch(self.bridge, 'GET', self.route + '?search=fixture&scope=personal')
        self.assertEqual(len(page['plugins']), 36); self.assertIsNone(page['nextCursor'])
        self.assertEqual(self.requests, self.baseline_requests)
