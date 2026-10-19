import copy
import unittest
from unittest.mock import patch
import test_console
from carryon.accounts.member_management import manage
from carryon.workspaces.workspace_access import granted
from carryon.workspaces.authorization import authority


class SharedWorkspaceAuthorizationTests(unittest.TestCase):
    tearDown = test_console.ConsoleTests.tearDown
    call = test_console.ConsoleTests.call
    login = test_console.ConsoleTests.login
    def setUp(self):
        test_console.ConsoleTests.setUp(self)
        self.workspace = {'id': 'f'*32, 'name': '电脑', 'backend': 'codex-cli'}
        self.server.config['devices']['my-mac']['workspace'] = {**self.workspace, 'backend': 'desktop-ipc'}
        self.credentials = {'deviceId': 'my-mac', 'token': 'd'*40}
        self.login()
        self.key = next(iter(self.server.sessions))

    def preview(self): return manage(self.server, {**self.credentials, 'action': 'connection-preview'})
    def attach(self, **fields):
        return manage(self.server, {**self.credentials, 'action': 'connection-attach', 'requestId': '1'*32,
                      'confirmed': True, 'revision': self.preview()['revision'], 'workspace': self.workspace, **fields})

    def test_single_authority_and_future_revoke_apply_to_both_transports(self):
        child = self.attach()['deviceId']
        self.assertNotIn('members', self.server.config['devices'][child])
        self.assertIn('approve', granted(self.server, self.key, child))
        manage(self.server, {**self.credentials, 'action': 'grant', 'accountId': 'owner', 'permissions': ['view']})
        self.assertEqual(granted(self.server, self.key, child), ['view'])
        manage(self.server, {**self.credentials, 'action': 'revoke', 'accountId': 'owner'})
        self.assertEqual(granted(self.server, self.key, child), [])
        self.assertEqual(granted(self.server, self.key, 'my-mac'), [])
        self.assertIn('view', granted(self.server, self.key, 'other'))

    def test_attach_requires_credentials_confirmation_and_fresh_members(self):
        before = copy.deepcopy(self.server.config['devices'])
        for extra in ({'token': 'x'*40}, {'confirmed': False}, {'revision': 'stale'}, {'workspace': {**self.workspace, 'id': 'e'*32}}):
            with self.subTest(extra=extra), self.assertRaises(PermissionError): self.attach(**extra)
            self.assertEqual(self.server.config['devices'], before)
        revision = self.preview()['revision']
        manage(self.server, {**self.credentials, 'action': 'grant', 'accountId': 'owner', 'permissions': ['view']})
        with self.assertRaises(PermissionError): self.attach(revision=revision)

    def test_retry_same_credentials_but_revoked_attachment_cannot_resurrect(self):
        result = self.attach()
        self.assertEqual(self.attach(), result)
        self.server.revoke_device(result['deviceId'])
        with self.assertRaisesRegex(PermissionError, '撤销'): self.attach()

    def test_remove_authority_connection_promotes_without_losing_members(self):
        child = self.attach()
        self.server.revoke_device('my-mac')
        root_id, root = authority(self.server.config['devices'], child['deviceId'])
        self.assertEqual(root_id, child['deviceId'])
        self.assertIn('approve', granted(self.server, self.key, child['deviceId']))
        with self.assertRaises(PermissionError): self.preview()
        self.credentials = {'deviceId': child['deviceId'], 'token': child['token']}
        self.assertEqual(self.attach(), child)
        manage(self.server, {**self.credentials, 'action': 'revoke', 'accountId': 'owner'})
        self.assertEqual(granted(self.server, self.key, child['deviceId']), [])

    def test_failed_save_does_not_half_link_authority(self):
        original = copy.deepcopy(self.server.config['devices'])
        with patch.object(self.server, 'save_devices', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.attach()
        self.assertEqual(self.server.config['devices'], original)

    def test_cyclic_or_missing_authority_fails_closed(self):
        self.server.config['devices']['my-mac']['workspaceAuthority'] = 'missing'
        self.assertEqual(granted(self.server, self.key, 'my-mac'), [])

    def test_browser_cannot_attach_and_phone_directory_shares_permissions(self):
        self.assertEqual(self.call('POST', '/console/binding/manage', {**self.credentials, 'action': 'connection-preview'})[0], 403)
        child = self.attach()['deviceId']
        rows = {row['id']: row for row in self.call('GET', '/console/session')[1]['devices']}
        self.assertEqual(rows[child]['workspace']['id'], rows['my-mac']['workspace']['id'])
        self.assertEqual(rows[child]['permissions'], rows['my-mac']['permissions'])


    def test_concurrent_retries_create_one_connection(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.attach(), range(8)))
        self.assertTrue(all(item == results[0] for item in results))
        self.assertEqual(len(self.server.config['devices']), 3)

    def test_shared_authority_survives_registry_reload(self):
        import json
        from carryon.cloud.console import ConsoleServer
        self.server.registry_path = self.root/'devices.json'
        child = self.attach()
        self.server.revoke_device('my-mac')
        restored = ConsoleServer(('127.0.0.1', 0), self.config, state_dir=self.root)
        try:
            root_id, root = authority(restored.config['devices'], child['deviceId'])
            self.assertEqual(root_id, child['deviceId'])
            self.assertIn('approve', root['members']['owner'])
            result = manage(restored, {'deviceId':child['deviceId'],'token':child['token'],'action':'list'})
            self.assertIn('approve', result['members'][0]['permissions'])
        finally: restored.server_close()
