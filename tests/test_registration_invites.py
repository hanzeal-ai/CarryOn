from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_console_auth import AccountTests
from carryon.console_auth import ConsoleAuth, password_record
from carryon import cli, invite_cli
from carryon.account_client import request as account_request


class RegistrationInvitesTests(AccountTests):
    def issue(self):
        token = 'issuer-secret-' + 'x' * 32
        self.server.config['registrationInviteIssuerHash'] = hashlib.sha256(token.encode()).hexdigest()
        status, data, _ = self.request('account/invite', {'issuerToken': token}, origin=False)
        self.assertEqual(status, 200, data)
        return data

    def test_only_designated_computer_can_issue(self):
        body = {'issuerToken': 'x' * 43}
        self.assertEqual(self.request('account/invite', body, origin=False)[0], 403)
        invite = self.issue()
        self.assertEqual(self.request('account/invite', body, origin=False)[0], 403)
        self.assertEqual(self.request('account/invite', {}, self.login(), origin=False)[0], 403)
        self.assertEqual(self.request('account/invite', {'issuerToken': 'issuer-secret-' + 'x' * 32})[0], 403)
        self.assertNotIn(invite['inviteCode'], (Path(self.temp.name) / 'registration-invites.json').read_text())

    def test_registration_requires_code_and_consumes_once_across_restart(self):
        body = {'username': 'alice', 'password': 'a long password 123'}
        for code in (None, '', 'unknown', []):
            self.assertEqual(self.request('register', {**body, 'inviteCode': code})[0], 400)
        invite = self.issue()
        status, _, cookie = self.request('register', {**body, **invite})
        self.assertEqual(status, 200)
        self.assertEqual(self.request('session', cookie=cookie)[1]['devices'], [])
        self.stop(); self.start()
        status, data, _ = self.request('register', {**body, 'username':'bob', **invite})
        self.assertEqual(status, 400)
        self.assertIn('已使用', data['error'])
        self.assertEqual(self.request('login', body)[0], 200)

    def test_failed_registration_leaves_invite_available(self):
        invite = self.issue()
        for body in ({'username':'admin', 'password':'a long password 123'},
                     {'username':'alice', 'password':'short'}):
            self.assertEqual(self.request('register', {**body, **invite})[0], 400)
        self.assertEqual(self.request('register', {'username':'alice', 'password':'a long password 123', **invite})[0], 200)

    def test_native_transport_and_issuer_replacement(self):
        token = 'issuer-secret-' + 'x' * 32
        self.issue()
        result = account_request(self.origin, 'invite', {'issuerToken':token}, dev_local=True)
        self.assertEqual(len(result['inviteCode']), 32)
        self.server.config['registrationInviteIssuerHash'] = hashlib.sha256(b'another computer').hexdigest()
        with self.assertRaisesRegex(ValueError, '未获授权'):
            account_request(self.origin, 'invite', {'issuerToken':token}, dev_local=True)


class InvitePersistenceTests(unittest.TestCase):
    def test_authorization_configuration_replaces_only_issuer(self):
        from carryon.console import main
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'console.json'
            original = {'publicUrl':'https://test.invalid', 'devices':{}, 'accountSetup':True}
            path.write_text(json.dumps(original))
            for digest in ('a' * 64, 'b' * 64):
                with patch('sys.argv', ['carryon-console', 'authorize-inviter', '--config', str(path), '--issuer-hash', digest]), patch('sys.stdout', new_callable=io.StringIO):
                    main()
                self.assertEqual(json.loads(path.read_text()), {**original, 'registrationInviteIssuerHash':digest})

    def test_directory_sync_failure_after_commit_cannot_reuse_code(self):
        from carryon.paths import save_json
        with tempfile.TemporaryDirectory() as directory:
            config = {'account': password_record('admin', 'a long password 123')}
            auth = ConsoleAuth(config, directory)
            body = {'username':'alice', 'password':'a long password 123', **auth.create_registration_invite()}
            def visible_commit_then_error(path, data):
                save_json(path, data)
                raise OSError('directory fsync failed')
            with patch.object(auth, 'save_registration', side_effect=visible_commit_then_error):
                with self.assertRaises(OSError): auth.register(body)
            self.assertEqual(len(auth.users), 1)
            self.assertNotEqual(auth.verify(body), 'owner')
            with self.assertRaisesRegex(ValueError, '已使用'):
                ConsoleAuth(config, directory).register({**body, 'username':'bob'})

    def test_concurrent_instances_and_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {'account': password_record('admin', 'a long password 123')}
            auth = ConsoleAuth(config, directory)
            invite = auth.create_registration_invite()
            body = {'username':'alice', 'password':'a long password 123', **invite}
            with patch('carryon.console_auth.save_json', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): auth.register(body)
            def register(index):
                try:
                    ConsoleAuth(config, directory).register({**body, 'username':str(index)})
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(register, range(4))), 1)
            self.assertEqual(len(json.loads((Path(directory) / 'users.json').read_text())), 1)

    def test_cli_uses_one_private_credential_and_never_prints_it(self):
        with tempfile.TemporaryDirectory() as directory, patch('carryon.invite_cli.Path.home', return_value=Path(directory)):
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(cli.main(['invate', '--setup']), 0)
                fingerprint = json.loads(output.getvalue())['issuerHash']
            token = invite_cli.issuer_token()
            self.assertEqual(hashlib.sha256(token.encode()).hexdigest(), fingerprint)
            self.assertEqual(invite_cli.issuer_token(), token)
            path = Path(directory) / 'Library/Application Support/CarryOn/invite-issuer/credential.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch('carryon.invite_cli.request', return_value={'inviteCode':'a'*32}) as request, patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(cli.main(['invate', '--url', 'https://test.invalid']), 0)
                self.assertNotIn(token, output.getvalue())
                request.assert_called_once_with('https://test.invalid', 'invite', {'issuerToken':token})
