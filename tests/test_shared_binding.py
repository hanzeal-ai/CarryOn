import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest
import test_shared_workspace_authorization as server_fixture
from carryon.accounts import shared_binding
from carryon.accounts.member_management import manage
from carryon.accounts.onboarding import exchange
from carryon.cloud.cloud_manager import CloudManager
from carryon.services import register
from carryon.workspaces.connections import descriptor


class SharedBindingTests(unittest.TestCase):
    tearDown = server_fixture.SharedWorkspaceAuthorizationTests.tearDown
    call = server_fixture.SharedWorkspaceAuthorizationTests.call
    login = server_fixture.SharedWorkspaceAuthorizationTests.login
    def setUp(self):
        server_fixture.SharedWorkspaceAuthorizationTests.setUp(self)
        self.env = patch.dict(os.environ, {'CARRYON_REGISTRY_DIR': str(self.root/'registry')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.desktop, self.cli = self.root/'desktop', self.root/'cli'
        self.desktop.mkdir(); self.cli.mkdir()
        source = register(self.desktop, name='电脑', backend='desktop-ipc', codex_home=self.root/'codex')
        register(self.cli, backend='codex-cli', codex_home=self.root/'codex')
        self.server.config['devices']['my-mac']['workspace'] = descriptor(source)
        CloudManager(None, self.desktop).configure({'enabled': True, 'url': 'wss://example.test/device', 'deviceId': 'my-mac', 'token': 'd'*40, 'control': True}, start=False)
        self.binding = next(iter(CloudManager.saved_bindings(self.desktop)))
        def request(url, action, body):
            self.assertEqual(url, 'https://example.test'); self.assertEqual(action, 'manage')
            return manage(self.server, body)
        self.request = patch('carryon.accounts.onboarding.request', side_effect=request)
        self.request.start(); self.addCleanup(self.request.stop)

    def share_preview(self):
        return exchange(self.cli, {'action':'share-preview', 'sourceDirectory':str(self.desktop), 'sourceBindingId':self.binding})
    def confirm(self, preview):
        return exchange(self.cli, {'action':'share-confirm', 'confirmed':True, 'shareConfirmation':preview['shareConfirmation'], 'autoStart':False})

    def test_preview_is_read_only_and_confirm_installs_independent_credentials(self):
        before = set(self.server.config['devices'])
        result = self.share_preview()
        self.assertEqual(set(self.server.config['devices']), before)
        self.assertEqual(CloudManager.saved_bindings(self.cli), {})
        saved = self.confirm(result)
        self.assertEqual(saved['state'], 'bound')
        config = next(iter(CloudManager.saved_bindings(self.cli).values()))
        self.assertNotEqual(config['deviceId'], 'my-mac'); self.assertNotEqual(config['token'], 'd'*40)
        self.assertTrue(config['control'])
        self.assertEqual(self.confirm(result)['deviceId'], config['deviceId'])
        self.assertEqual(len(self.server.config['devices']), len(before)+1)

    def test_lost_response_reuses_request_and_exposes_retry_after_restart(self):
        preview = self.share_preview()
        def lost(url, action, body):
            manage(self.server, body)
            raise OSError('response lost')
        with patch('carryon.accounts.onboarding.request', side_effect=lost):
            with self.assertRaises(OSError): self.confirm(preview)
        pending = shared_binding.pending_preview(self.cli)
        self.assertEqual(pending['shareConfirmation'], preview['shareConfirmation'])
        before = set(self.server.config['devices'])
        with self.assertRaisesRegex(ValueError, '待恢复'): self.share_preview()
        self.confirm(pending)
        self.assertEqual(set(self.server.config['devices']), before)

    def test_completed_journal_does_not_block_explicit_rebinding(self):
        preview = self.share_preview(); self.confirm(preview)
        manager = CloudManager(self.bridge, self.cli)
        key, connection = next(iter(manager.connections.items()))
        self.server.revoke_device(connection.config['deviceId'])
        manager.configure({'enabled':False, 'id':key}, start=False)
        other = self.share_preview()
        self.assertNotEqual(other['shareConfirmation'], preview['shareConfirmation'])
        self.confirm(other)

    def test_new_home_and_changed_source_credential_rejected_before_attach(self):
        other = self.root/'other'; other.mkdir()
        register(other, backend='codex-cli', codex_home=self.root/'other-home')
        with self.assertRaises(ValueError):
            exchange(other, {'action':'share-preview','sourceDirectory':str(self.desktop),'sourceBindingId':self.binding})
        preview = self.share_preview()
        record = json.loads((self.desktop/'cloud.json').read_text())
        record['bindings'][self.binding]['token'] = 'z'*40
        (self.desktop/'cloud.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, '配置已改变'): self.confirm(preview)

    def test_cli_interactive_retry_consumes_saved_confirmation(self):
        import io
        from types import SimpleNamespace
        from carryon.accounts.onboarding import command
        preview = self.share_preview()
        def lost(url, action, body):
            manage(self.server, body); raise OSError('response lost')
        with patch('carryon.accounts.onboarding.request', side_effect=lost):
            with self.assertRaises(OSError): self.confirm(preview)
        count = len(self.server.config['devices'])
        args = SimpleNamespace(input_json=False, state_dir=self.cli, url=None, permissions=None)
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='y') as prompt, patch('sys.stdout', new_callable=io.StringIO), patch('carryon.services.start', return_value=0):
            self.assertEqual(command(args), 0)
            self.assertEqual(prompt.call_count, 1)
        self.assertEqual(len(self.server.config['devices']), count)
        self.assertIsNone(shared_binding.pending_preview(self.cli))

    def test_second_cloud_pending_remains_visible_while_first_cloud_bound(self):
        from carryon.cloud.console import ConsoleServer
        self.confirm(self.share_preview())
        first = dict(CloudManager.saved_bindings(self.cli))
        config = {**self.config, 'devices': {'second': {'deviceToken':'z'*40, 'apiToken':'y'*40, 'ownerUserId':'owner', 'members':{'owner':['view']}}}}
        other = ConsoleServer(('127.0.0.1', 0), config)
        self.addCleanup(other.server_close)
        manager = CloudManager(None, self.desktop)
        manager.configure({'enabled':True,'url':'wss://second.example.test/device','deviceId':'second','token':'z'*40,'control':False}, start=False)
        binding = next(key for key, value in CloudManager.saved_bindings(self.desktop).items() if value['deviceId']=='second')
        def routed(url, action, body):
            self.assertEqual(action, 'manage')
            if url == 'https://second.example.test':
                self.assertEqual(body['token'], 'z'*40)
                return manage(other, body)
            self.assertEqual(url, 'https://example.test')
            return manage(self.server, body)
        with patch('carryon.accounts.onboarding.request', side_effect=routed):
            preview = exchange(self.cli, {'action':'share-preview','sourceDirectory':str(self.desktop),'sourceBindingId':binding})
            def lost(url, action, body):
                routed(url, action, body); raise OSError('response lost')
            with patch('carryon.accounts.onboarding.request', side_effect=lost):
                with self.assertRaises(OSError): self.confirm(preview)
            status = exchange(self.cli, {'action':'status'})
            self.assertEqual(status['state'], 'bound')
            self.assertEqual(status['sharedPending']['shareConfirmation'], preview['shareConfirmation'])
            self.confirm(status['sharedPending'])
        bindings = CloudManager.saved_bindings(self.cli)
        self.assertEqual(len(bindings), 2)
        self.assertEqual({key:bindings[key] for key in first}, first)

    def test_cancel_unsubmitted_preview_but_keep_uncertain_join(self):
        preview = self.share_preview()
        exchange(self.cli, {'action':'share-cancel'})
        self.assertIsNone(shared_binding.pending_preview(self.cli))
        with self.assertRaises(ValueError): self.confirm(preview)
        preview = self.share_preview()
        def lost(url, action, body):
            manage(self.server, body); raise OSError('response lost')
        with patch('carryon.accounts.onboarding.request', side_effect=lost):
            with self.assertRaises(OSError): self.confirm(preview)
        with self.assertRaisesRegex(ValueError, '尚未确认'):
            exchange(self.cli, {'action':'share-cancel'})
        self.assertEqual(shared_binding.pending_preview(self.cli)['shareConfirmation'], preview['shareConfirmation'])
        self.confirm(preview)
