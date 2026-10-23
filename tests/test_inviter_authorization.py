import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_console_auth import AccountTests
from carryon import cli
from carryon.accounts import invite_cli
from carryon.cloud.console_auth import password_record
from carryon.accounts.inviter_authorization import record_path


class InviterAuthorizationTests(AccountTests):
    token = 'new-computer-' + 'x' * 32

    def approval(self, **changes):
        return {'username': 'admin', 'password': 'a long password 123',
                'issuerHash': hashlib.sha256(self.token.encode()).hexdigest(), 'confirm': True, **changes}

    def issue(self, token=None):
        return self.request('account/invite', {'issuerToken': token or self.token}, origin=False)

    def test_remote_approval_effective_immediately_persistent_and_regular_registration(self):
        self.assertEqual(self.issue()[0], 403)
        status, result, cookie = self.request('inviter/authorize', self.approval())
        self.assertEqual(status, 200, result)
        self.assertTrue(result['authorized']); self.assertEqual(cookie, '')
        status, invite, _ = self.issue(); self.assertEqual(status, 200)
        body = {'username': 'ordinary-test', 'password': 'test-password-123', **invite}
        status, _, cookie = self.request('register', body); self.assertEqual(status, 200)
        session = self.request('session', cookie=cookie)[1]
        self.assertNotEqual(session['account']['id'], 'owner'); self.assertEqual(session['devices'], [])
        record = record_path(self.server)
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.token, record.read_text())
        self.assertNotIn(self.approval()['password'], record.read_text())
        self.stop(); self.start()
        self.assertEqual(self.issue()[0], 200)

    def test_only_explicit_owner_credentials_and_same_origin_grant(self):
        body = self.approval()
        self.assertEqual(self.request('inviter/authorize', body, origin=False)[0], 403)
        original = self.origin
        self.origin = 'https://foreign.invalid'
        try: self.assertEqual(self.request('inviter/authorize', body)[0], 403)
        finally: self.origin = original
        self.assertEqual(self.request('inviter/authorize', self.approval(password='wrong'))[0], 403)
        self.assertEqual(self.request('inviter/authorize', self.approval(confirm=False))[0], 400)
        self.assertEqual(self.request('inviter/authorize', {'issuerHash': body['issuerHash'], 'confirm': True}, self.login())[0], 403)
        self.server.auth.users['member'] = password_record('member', 'member-password-123')
        self.assertEqual(self.request('inviter/authorize', self.approval(username='member', password='member-password-123'))[0], 403)
        self.assertEqual(self.issue()[0], 403)
        self.assertFalse((record_path(self.server)).exists())

    def test_invalid_payload_and_get_cannot_grant(self):
        self.assertNotEqual(self.request('inviter/authorize')[0], 200)
        for value in ([], {}, {'issuerHash': 'x' * 64}, self.approval(issuerHash='a'*63), self.approval(issuerHash='A'*64)):
            self.assertEqual(self.request('inviter/authorize', value)[0], 400)
        self.assertEqual(self.issue()[0], 403)

    def test_replacement_revokes_previous_issuer_without_restart_and_replay_is_idempotent(self):
        old = 'old-computer-' + 'y'*32
        self.server.config['registrationInviteIssuerHash'] = hashlib.sha256(old.encode()).hexdigest()
        self.assertEqual(self.issue(old)[0], 200)
        for _ in range(2): self.assertEqual(self.request('inviter/authorize', self.approval())[0], 200)
        self.assertEqual(self.issue(old)[0], 403)
        self.assertEqual(self.issue()[0], 200)
        self.assertNotIn('inviter', self.request('session', cookie=self.login())[1])

    def test_server_recovery_configuration_supersedes_remote_grant(self):
        self.assertEqual(self.request('inviter/authorize', self.approval())[0], 200)
        self.stop()
        replacement = 'recovery-computer-' + 'z' * 32
        self.config['registrationInviteIssuerHash'] = hashlib.sha256(replacement.encode()).hexdigest()
        self.start()
        self.assertEqual(self.issue()[0], 403)
        self.assertEqual(self.issue(replacement)[0], 200)

    def test_storage_failure_never_reports_success_and_corruption_fails_closed(self):
        with patch('carryon.accounts.inviter_authorization.save_json', side_effect=OSError('disk full')):
            status, result, _ = self.request('inviter/authorize', self.approval())
        self.assertEqual(status, 503); self.assertTrue(result['uncertain'])
        self.assertEqual(self.issue()[0], 403)
        (record_path(self.server)).write_text('{}')
        self.assertEqual(self.issue()[0], 400)

    def test_visible_commit_then_sync_failure_is_recoverable_without_retrying_write(self):
        from carryon.paths import save_json
        def save_then_fail(path, value):
            save_json(path, value)
            raise OSError('after rename')
        with patch('carryon.accounts.inviter_authorization.save_json', side_effect=save_then_fail):
            self.assertEqual(self.request('inviter/authorize', self.approval())[0], 503)
        self.assertEqual(self.issue()[0], 200)
        with patch('carryon.accounts.inviter_authorization.os.fsync', side_effect=OSError('sync failed')):
            self.assertEqual(self.request('inviter/authorize', self.approval())[0], 503)
        self.assertEqual(self.request('inviter/authorize', self.approval())[0], 200)

    def test_null_record_does_not_reenable_old_configured_issuer(self):
        self.server.config['registrationInviteIssuerHash'] = hashlib.sha256(self.token.encode()).hexdigest()
        record_path(self.server).write_text('null')
        self.assertEqual(self.issue()[0], 400)

    def test_operator_can_restore_same_original_hash_even_with_corrupt_record(self):
        from carryon.cloud.console import main
        original = hashlib.sha256(self.token.encode()).hexdigest()
        self.config['registrationInviteIssuerHash'] = original
        self.server.config['registrationInviteIssuerHash'] = original
        self.assertEqual(self.request('inviter/authorize', self.approval(issuerHash='b'*64))[0], 200)
        for corrupt in (False, True):
            if corrupt: record_path(self.server).write_text('broken')
            self.stop()
            config_path = Path(self.temp.name) / 'config.json'
            config_path.write_text(json.dumps(self.config))
            with patch('sys.argv', ['console', 'authorize-inviter', '--config', str(config_path), '--issuer-hash', original]), patch('sys.stdout', new_callable=io.StringIO):
                main()
            self.config = json.loads(config_path.read_text())
            self.start()
            self.assertEqual(self.issue()[0], 200)

    def test_separate_instances_observe_authorization_and_serialize_replacement(self):
        from concurrent.futures import ThreadPoolExecutor
        from carryon.cloud.console import ConsoleServer
        from carryon.accounts.inviter_authorization import authorize, issuer_hash
        other = ConsoleServer(('127.0.0.1', 0), self.config, self.temp.name)
        try:
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda pair: authorize(pair[0], self.approval(issuerHash=pair[1])),
                                        [(self.server, 'a'*64), (other, 'b'*64)]))
            self.assertTrue(all(result['authorized'] for result in results))
            with other.account_settings.locked():
                current = issuer_hash(other)
            self.assertIn(current, ('a'*64, 'b'*64))
            with self.server.account_settings.locked():
                self.assertEqual(issuer_hash(self.server), current)
        finally:
            other.server_close()

    def test_recovery_password_change_rejects_old_password(self):
        self.assertEqual(self.request('account/change', {'currentUsername':'admin', 'currentPassword':'a long password 123',
            'username':'admin', 'password':'changed-password-456'}, origin=False)[0], 200)
        self.assertEqual(self.request('inviter/authorize', self.approval())[0], 403)
        self.assertEqual(self.request('inviter/authorize', self.approval(password='changed-password-456'))[0], 200)

    def test_authorization_throttled_using_existing_auth_limiter(self):
        for _ in range(10):
            self.assertEqual(self.request('inviter/authorize', self.approval(password='wrong'))[0], 403)
        status, result, _ = self.request('inviter/authorize', self.approval())
        self.assertEqual(status, 403); self.assertIn('频繁', result['error'])


class AuthorizationLinkTests(unittest.TestCase):
    def test_cli_link_uses_public_hash_not_credential_and_preserves_prefix(self):
        with tempfile.TemporaryDirectory() as directory, patch('carryon.accounts.invite_cli.Path.home', return_value=Path(directory)):
            token = invite_cli.issuer_token()
            with patch('sys.stdout', new_callable=io.StringIO) as output, patch('carryon.accounts.invite_cli.request') as request:
                self.assertEqual(cli.main(['invate', '--authorize', '--url', 'https://test.invalid/carryon/']), 0)
            result = json.loads(output.getvalue())
            self.assertNotIn(token, output.getvalue()); request.assert_not_called()
            self.assertEqual(result['authorizationUrl'], 'https://test.invalid/carryon/#carryon-inviter=' + hashlib.sha256(token.encode()).hexdigest())

    def test_cli_rejects_unsafe_authorization_urls(self):
        with patch('carryon.accounts.invite_cli.issuer_token', return_value='x'*43):
            for url in ('http://localhost', 'https://test.invalid/#x', 'https://user:pass@test.invalid', 'https://test.invalid/?x'):
                with patch('sys.stderr', new_callable=io.StringIO):
                    self.assertEqual(cli.main(['invate', '--authorize', '--url', url]), 1)
