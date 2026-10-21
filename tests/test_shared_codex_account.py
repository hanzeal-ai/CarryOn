import base64
import datetime
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from carryon.app_server.app_server import AppServer
from carryon.app_server.shared_account import SharedAccount, source_home
from carryon.errors import IPCError


def jwt(account='account-a'):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    return encode({'alg': 'none'}) + '.' + encode({
        'sub': 'fixture', 'email': 'fixture@example.test', 'exp': 4102444800,
        'https://api.openai.com/auth': {'chatgpt_account_id': account, 'chatgpt_plan_type': 'plus'}
    }) + '.fixture'


class SharedAccountTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.account_ready = False
        self.client.lock = threading.RLock()
        self.account = SharedAccount(self.client)

    def test_sync_changes_and_logout_do_not_persist_credentials(self):
        first = {'type': 'apiKey', 'apiKey': 'fixture-a'}
        second = {'type': 'apiKey', 'apiKey': 'fixture-b'}
        with patch.object(self.account, 'read', side_effect=[first, first, second, None]):
            self.account.sync(); self.account.sync()
            self.client.rpc.assert_called_once_with('account/login/start', first)
            self.account.sync()
            self.client.rpc.assert_called_with('account/login/start', second)
            self.account.sync()
        self.client.rpc.assert_called_with('account/logout', {})
        self.assertFalse(self.client.account_ready)
        self.assertIsNone(self.account.fingerprint)

    def test_unreadable_source_fails_closed_without_exposing_native_error(self):
        self.client.account_ready = True
        with patch.object(self.account, 'read', side_effect=IPCError('secret-token-fixture')):
            with self.assertRaises(IPCError) as error:
                self.account.sync()
        self.assertNotIn('secret-token', str(error.exception))
        self.assertFalse(self.client.account_ready)
        self.client.rpc.assert_called_with('account/logout', {})

    def test_refresh_uses_source_and_rejects_account_switch(self):
        event = {'id': 'refresh-1', 'params': {'previousAccountId': 'a'}}
        credentials = {'type': 'chatgptAuthTokens', 'accessToken': 'fixture', 'chatgptAccountId': 'a'}
        with patch.object(self.account, 'read', return_value=credentials) as read:
            self.account.refresh(event, self.client.process)
            read.assert_called_once_with(refresh=True)
        self.client._write.assert_called_with({'id': 'refresh-1', 'result': {
            'accessToken': 'fixture', 'chatgptAccountId': 'a'}})
        credentials['chatgptAccountId'] = 'b'
        with patch.object(self.account, 'read', return_value=credentials):
            self.account.refresh(event, self.client.process)
        self.assertIn('error', self.client._write.call_args.args[0])
        self.assertFalse(self.client.account_ready)

    def test_refresh_after_reconnect_cannot_write_to_new_process(self):
        self.client.account_ready = True
        with patch.object(self.account, 'read', return_value=None):
            self.account.refresh({'id': 7}, object())
        self.client._write.assert_not_called()
        self.assertTrue(self.client.account_ready)

    def test_cli_login_uses_source_home_not_workspace(self):
        from carryon.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); workspace = root / 'workspace'; source = root / 'source'
            with patch('carryon.services.records', return_value={str(workspace): {'backend': 'app-server', 'codexHome': str(workspace / 'codex')}}), \
                    patch('carryon.app_server.shared_account.source_home', return_value=source), \
                    patch('carryon.usage.executable', return_value='fixture-codex'), \
                    patch('carryon.cli.subprocess.call', return_value=0) as call:
                self.assertEqual(main(['services', 'login', '--state-dir', str(workspace)]), 0)
                self.assertEqual(call.call_args.kwargs['env']['CODEX_HOME'], str(source))
                self.assertEqual(call.call_args.kwargs['cwd'], str(source))

    def test_closed_account_does_not_restart_login_or_sync(self):
        self.account.close()
        with self.assertRaises(IPCError): self.account.sync()
        with self.assertRaises(IPCError): self.account.start_login()

    def test_peer_preserves_sharing_and_workspace_home(self):
        parent = AppServer('/tmp/fixture-workspace', shared_account=True)
        peer = parent.peer(runtime_directory='/tmp/fixture-side')
        self.assertEqual(peer.home, parent.home)
        self.assertIsNotNone(peer.shared_account)

    def test_registered_desktop_home_is_authoritative(self):
        with patch('carryon.services.records', return_value={
            'removed': {'backend': 'desktop-ipc', 'removed': True, 'codexHome': '/tmp/old'},
            'desktop': {'backend': 'desktop-ipc', 'codexHome': '/tmp/desktop'},
            'cli': {'backend': 'codex-cli', 'codexHome': '/tmp/cli'}}):
            self.assertEqual(source_home(), Path('/tmp/desktop').resolve())

    def test_malformed_native_credentials_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.client.home = Path(directory) / 'workspace'
            self.client.runtime_directory = Path(directory) / 'runtime'
            reader = Mock()
            for response in [None, [], {'authMethod': 'apikey', 'authToken': 12},
                             {'authMethod': 'chatgpt', 'authToken': 'invalid'},
                             {'authMethod': 'chatgpt', 'authToken': '.bnVsbA.'},
                             {'authMethod': 'apikey', 'authToken': ''}]:
                with self.subTest(response=response), patch('carryon.app_server.shared_account.source_home', return_value=Path(directory)), \
                        patch('carryon.app_server.app_server.AppServer', return_value=reader):
                    reader.rpc.return_value = response
                    with self.assertRaises(IPCError): self.account._read()
            reader.close.assert_called()

    def test_quota_uses_shared_source_only_for_owned_workspaces(self):
        from carryon.app_server.shared_account import account_home
        bridge = Mock(); bridge.backend = 'app-server'; bridge.catalog.home = Path('/tmp/isolated')
        with patch('carryon.app_server.shared_account.source_home', return_value=Path('/tmp/source')):
            self.assertEqual(account_home(bridge), Path('/tmp/source'))
            for backend in ('codex-cli', 'desktop-ipc'):
                bridge.backend = backend
                self.assertEqual(account_home(bridge), Path('/tmp/isolated'))

    def test_concurrent_syncs_only_install_one_token(self):
        with patch.object(self.account, 'read', return_value={'type': 'apiKey', 'apiKey': 'fixture'}):
            threads = [threading.Thread(target=self.account.sync) for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=2)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.client.rpc.assert_called_once()

    def test_login_targets_source_and_close_releases_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            self.client.runtime_directory = Path(directory) / 'workspace'
            source = Path(directory) / 'source'
            reader = Mock()
            with patch('carryon.app_server.shared_account.source_home', return_value=source), \
                    patch('carryon.app_server.app_server.AppServer', return_value=reader) as constructor:
                self.account.start_login()
                self.assertEqual(constructor.call_args.args[0], source)
                reader.rpc.assert_called_with('account/login/start', {'type': 'chatgpt'})
                self.account.close()
                reader.close.assert_called_once()

    def test_failed_refresh_does_not_expose_error_or_token(self):
        with patch.object(self.account, 'read', side_effect=IPCError('secret-fixture')):
            self.account.refresh({'id': 3}, self.client.process)
        response = self.client._write.call_args.args[0]
        self.assertIn('error', response)
        self.assertNotIn('secret-fixture', json.dumps(response))

    def test_forced_refresh_is_serialized_across_processes(self):
        import subprocess
        import sys
        from carryon.app_server.initialization import initialization_lock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'account-sync').mkdir()
            program = '''
from unittest.mock import Mock, patch
from carryon.app_server.shared_account import SharedAccount
from carryon.errors import IPCError
with patch.object(SharedAccount, '_read', return_value='entered') as read:
    try:
        print(SharedAccount(Mock()).read(refresh=True))
    except IPCError:
        assert not read.called
        print('locked')
'''
            env = dict(os.environ, CARRYON_REGISTRY_DIR=str(root))
            with initialization_lock(root / 'account-sync'):
                result = subprocess.run([sys.executable, '-c', program], env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'locked')
            result = subprocess.run([sys.executable, '-c', program], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'entered')


class NativeSharedAccountTests(unittest.TestCase):
    def setUp(self):
        from carryon.usage import executable
        try:
            executable()
        except Exception:
            self.skipTest('installed Codex required')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        env = patch.dict(os.environ, {'CARRYON_REGISTRY_DIR': str(self.root / 'registry'), 'CODEX_HOME': str(self.source)})
        env.start(); self.addCleanup(env.stop)

    def server(self, name):
        home = self.root / name; home.mkdir()
        server = AppServer(home, shared_account=True)
        self.addCleanup(server.close)
        return server

    def key(self, value):
        (self.source / 'auth.json').write_text(json.dumps({'OPENAI_API_KEY': value}))

    def test_two_workspaces_share_auth_but_not_threads_or_files(self):
        self.key('sk-fixture-shared')
        a, b = self.server('a'), self.server('b')
        # Thread creation must not depend on the public model-catalog network.
        # No turn is sent; the unreachable fixture provider is never invoked.
        for server in (a, b):
            (server.home / 'config.toml').write_text(
                'model_provider = "fixture"\n[model_providers.fixture]\n'
                'name = "fixture"\nbase_url = "http://127.0.0.1:1"\n'
                'wire_api = "responses"\nrequires_openai_auth = true\n')
        old = json.dumps({'OPENAI_API_KEY': 'sk-fixture-old-workspace'})
        (a.home / 'auth.json').write_text(old)
        a.connect(); b.connect()
        for server in (a, b):
            self.assertTrue(server.account_ready)
            native = server.rpc('getAuthStatus', {'includeToken': True, 'refreshToken': False})
            self.assertEqual(native['authToken'], 'sk-fixture-shared')
        thread = a.rpc('thread/start', {'cwd': str(a.home), 'approvalPolicy': 'on-request', 'sandbox': 'workspace-write'})['thread']
        self.assertTrue(Path(thread['path']).is_relative_to(a.home))
        self.assertNotIn(thread['id'], [row['id'] for row in b.rpc('thread/list', {'limit': 100})['data']])
        with self.assertRaises(IPCError):
            b.rpc('thread/read', {'threadId': thread['id'], 'includeTurns': False})
        self.assertFalse((b.home / 'auth.json').exists())
        self.assertEqual((a.home / 'auth.json').read_text(), old)
        self.assertFalse((a.home / 'sessions').is_symlink())
        self.assertFalse((b.home / 'sessions').is_symlink())
        self.key('sk-fixture-switched')
        for server in (a, b):
            server.require_account()
            self.assertEqual(server.rpc('getAuthStatus', {'includeToken': True, 'refreshToken': False})['authToken'], 'sk-fixture-switched')
        (self.source / 'auth.json').unlink()
        for server in (a, b):
            with self.assertRaisesRegex(IPCError, '本机 Codex 尚未登录'):
                server.require_account()
            self.assertIsNone(server.rpc('account/read', {'refreshToken': False})['account'])
        self.assertEqual((a.home / 'auth.json').read_text(), old)

    def test_missing_login_can_be_added_without_restarting_workspace(self):
        server = self.server('a'); server.connect()
        self.assertFalse(server.account_ready)
        self.key('sk-fixture-added')
        server.require_account()
        self.assertTrue(server.account_ready)
        self.assertFalse((server.home / 'auth.json').exists())

    def test_chatgpt_external_tokens_with_cli_0155(self):
        # This installed release allows synthetic JWTs without routing discovery
        # network requests. No model call, real credential or refresh is used.
        codex = shutil.which('codex')
        if not codex:
            self.skipTest('standalone Codex CLI required')
        import subprocess
        if '0.155.1' not in subprocess.check_output([codex, '--version'], text=True):
            self.skipTest('synthetic ChatGPT fixture validated against CLI 0.155.1')
        token = jwt()
        (self.source / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {
            'access_token': token, 'id_token': token, 'refresh_token': 'fixture-refresh', 'account_id': 'account-a'},
            'last_refresh': datetime.datetime.now(datetime.timezone.utc).isoformat()}))
        server = self.server('a')
        with patch('carryon.app_server.app_server.executable', return_value=codex):
            server.connect()
            self.assertTrue(server.account_ready)
            self.assertEqual(server.rpc('account/read', {'refreshToken': False})['account']['type'], 'chatgpt')
            self.assertFalse((server.home / 'auth.json').exists())
            server.close()


if __name__ == '__main__':
    unittest.main()
