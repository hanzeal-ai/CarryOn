import concurrent.futures
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from carryon.account_client import request
from carryon.account_settings import AccountSettings
from carryon.console import ConsoleServer
from carryon.console_auth import ConsoleAuth, password_record
from carryon.cli import main

PASSWORD = 'initial-password-123'
NEW_PASSWORD = 'changed-password-456'


class AccountSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.config = {'publicUrl': 'http://127.0.0.1', 'accountSetup': True,
                       'devices': {'mac': {'deviceToken': 'd'*40, 'apiToken': 'a'*40}}}
        self.start()

    def start(self):
        self.server = ConsoleServer(('127.0.0.1', 0), self.config, self.directory)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.server.origin = self.url
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(3)

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def http(self, route, data=None, cookie='', origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'Content-Type': 'application/json', 'Cookie': cookie}
        if origin: headers['Origin'] = origin
        conn.request('GET' if data is None else 'POST', '/console/'+route,
                     json.dumps(data) if data is not None else None, headers)
        response = conn.getresponse()
        value = json.loads(response.read()); cookie = response.getheader('Set-Cookie')
        status = response.status; conn.close()
        return status, value, cookie

    def setup_account(self):
        token = AccountSettings(self.config, self.directory).bootstrap()
        result = request(self.url, 'setup', {'setupToken': token, 'username': 'admin', 'password': PASSWORD}, dev_local=True)
        self.assertTrue(result['changed'])
        return token

    def change(self, **extra):
        return self.http('account/change', {'currentUsername': 'admin', 'currentPassword': PASSWORD,
                                          'username': 'owner', 'password': NEW_PASSWORD, **extra})

    def test_setup_single_use_restart_and_no_credentials_in_storage(self):
        token = self.setup_account()
        raw = (self.directory/'account.json').read_text()
        self.assertNotIn(token, raw); self.assertNotIn(PASSWORD, raw)
        self.assertEqual((self.directory/'account.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.http('account/setup', {'setupToken': token, 'username': 'x', 'password': PASSWORD})[0], 403)
        with self.assertRaises(ValueError):AccountSettings(self.config, self.directory).bootstrap()
        self.stop(); self.start()
        self.assertTrue(request(self.url, 'status', dev_local=True)['configured'])
        self.assertEqual(self.http('login', {'username': 'admin', 'password': PASSWORD}, origin=self.url)[0], 200)
        self.assertEqual(self.http('login', {'token': 't'*40}, origin=self.url)[0], 403)
        self.assertEqual(self.server.config['devices'], self.config['devices'])

    def test_existing_password_account_survives_retired_token_login_removal(self):
        self.stop()
        self.config.pop('accountSetup')
        self.config['consoleToken'] = 'retired-recovery-source-' + 'x' * 32
        account = password_record('admin', PASSWORD)
        # Fixture uses the deployed record format, not the current authority helper.
        source = hashlib.sha256(json.dumps({'consoleToken': self.config['consoleToken']}, sort_keys=True).encode()).hexdigest()
        record = {'version': 1, 'source': source, 'account': account, 'generation': 'a' * 64}
        path = self.directory / 'account.json'
        path.write_text(json.dumps(record))
        before = path.read_bytes()
        self.start()
        self.assertEqual(self.server.auth.account, account)
        self.assertEqual(self.server.config['devices'], self.config['devices'])
        status, _, cookie = self.http('login', {'username': 'admin', 'password': PASSWORD}, origin=self.url)
        self.assertEqual(status, 200)
        self.assertEqual(self.http('login', {'token': self.config['consoleToken']}, origin=self.url)[0], 403)
        self.assertEqual(self.http('login', {'username': 'admin', 'password': 'wrong'}, origin=self.url)[0], 403)
        self.stop(); self.start()
        self.assertEqual(self.http('session', cookie=cookie)[0], 200)
        self.assertEqual(path.read_bytes(), before)

        # A different or removed recovery source must never adopt this account.
        for config in ({**self.config, 'consoleToken': 'different-' + 'y' * 32},
                       {k: v for k, v in self.config.items() if k != 'consoleToken'}):
            effective = AccountSettings(config, self.directory).effective()
            self.assertNotIn('account', effective)
            with self.assertRaises(ValueError):
                ConsoleAuth(effective, self.directory)
        # Token-only configurations still cannot start an authenticated console.
        with self.assertRaises(ValueError):
            ConsoleAuth(self.config, None)

    def test_bootstrap_expiry_replacement_and_invalid_submission_preserves_code(self):
        store = AccountSettings(self.config, self.directory)
        first = store.bootstrap(); second = store.bootstrap()
        body = {'setupToken': first, 'username': 'admin', 'password': PASSWORD}
        self.assertEqual(self.http('account/setup', body)[0], 403)
        self.assertEqual(self.http('account/setup', {**body, 'setupToken': second, 'password': 'short'})[0], 400)
        with store.locked():
            saved = store.read(); saved['setup']['expires'] = time.time()-1; store.save({'setup': saved['setup']})
        self.assertEqual(self.http('account/setup', {**body, 'setupToken': second})[0], 403)
        self.setup_account()

    def test_concurrent_redemption_has_one_winner(self):
        token = AccountSettings(self.config, self.directory).bootstrap()
        def attempt(index):
            return self.http('account/setup', {'setupToken': token, 'username': str(index), 'password': PASSWORD})[0]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:statuses = list(pool.map(attempt, range(2)))
        self.assertEqual(sorted(statuses), [200, 403])

    def test_change_requires_current_password_revokes_sessions_qr_codes_and_authority(self):
        self.setup_account()
        _, _, cookie = self.http('login', {'username': 'admin', 'password': PASSWORD}, origin=self.url)
        self.http('qr/create', {}, cookie, self.url)
        old_authority = self.server.auth.fingerprint
        self.assertEqual(self.change(currentPassword='wrong')[0], 403)
        self.assertEqual(self.change(currentUsername='other')[0], 403)
        self.assertEqual(self.http('account/change', {'username': 'owner', 'password': NEW_PASSWORD}, cookie)[0], 403)
        self.assertEqual(self.http('account/change', {'token': 'd'*40})[0], 403)
        self.assertEqual(self.change()[0], 200)
        self.assertNotEqual(self.server.auth.fingerprint, old_authority)
        self.assertFalse(self.server.auth.qrs)
        self.assertEqual(self.http('session', cookie=cookie)[0], 401)
        self.stop(); self.start()
        self.assertEqual(self.http('session', cookie=cookie)[0], 401)
        self.assertEqual(self.http('login', {'username': 'owner', 'password': NEW_PASSWORD}, origin=self.url)[0], 200)

    def test_native_endpoint_rejects_browser_origin_and_global_rate_limit(self):
        token = AccountSettings(self.config, self.directory).bootstrap()
        body = {'setupToken': token, 'username': 'admin', 'password': PASSWORD}
        for origin in (self.url, 'https://evil.invalid'):
            self.assertEqual(self.http('account/setup', body, origin=origin)[0], 403)
        for _ in range(10):self.assertEqual(self.http('account/setup', {**body, 'setupToken': 'x'*40})[0], 403)
        self.assertEqual(self.http('account/setup', body)[0], 403)
        self.server.auth.attempts = [time.monotonic()-61]
        self.assertEqual(self.http('account/setup', body)[0], 200)

    def test_failed_persistence_does_not_change_account_or_consume_token(self):
        token = AccountSettings(self.config, self.directory).bootstrap()
        body = {'setupToken': token, 'username': 'admin', 'password': PASSWORD}
        with patch('carryon.account_settings.save_json', side_effect=OSError('disk full')):
            self.assertEqual(self.http('account/setup', body)[0], 503)
        self.assertIsNone(self.server.auth.account)
        self.assertEqual(self.http('account/setup', body)[0], 200)
        fingerprint = self.server.auth.fingerprint
        with patch('carryon.account_settings.save_json', side_effect=OSError('disk full')):
            self.assertEqual(self.change()[0], 503)
        self.assertEqual(fingerprint, self.server.auth.fingerprint)

    def test_directory_fsync_failure_reports_unknown_and_revokes_visible_old_authority(self):
        import stat
        self.setup_account()
        _,_,cookie=self.http('login',{'username':'admin','password':PASSWORD},origin=self.url)
        real_fsync=os.fsync
        calls=[]
        def fsync(fd):
            is_directory=stat.S_ISDIR(os.fstat(fd).st_mode)
            calls.append(is_directory)
            if is_directory:raise OSError('directory sync failed')
            return real_fsync(fd)
        with patch('carryon.account_settings.os.fsync',side_effect=fsync):
            self.assertEqual(self.change()[0],503)
        self.assertEqual(calls,[False,True])
        self.assertEqual(self.http('session',cookie=cookie)[0],401)
        self.assertEqual(self.http('login',{'username':'owner','password':NEW_PASSWORD},origin=self.url)[0],200)

    def test_server_recovery_config_overrides_remote_account(self):
        self.setup_account(); self.stop()
        self.config['account'] = password_record('recovery', NEW_PASSWORD)
        self.start()
        self.assertEqual(self.http('login', {'username': 'admin', 'password': PASSWORD}, origin=self.url)[0], 403)
        self.assertEqual(self.http('login', {'username': 'recovery', 'password': NEW_PASSWORD}, origin=self.url)[0], 200)

    def test_exact_config_backup_restore_does_not_revive_old_session(self):
        self.stop()
        self.config['account']=password_record('admin', PASSWORD)
        self.start()
        _,_,cookie=self.http('login',{'username':'admin','password':PASSWORD},origin=self.url)
        old=self.server.auth.fingerprint
        self.assertEqual(self.change()[0],200)
        self.stop()
        # The original config is unchanged: simulate rolling back only config/credentials.
        record=json.loads((self.directory/'account.json').read_text())
        record['source']='f'*64
        (self.directory/'account.json').write_text(json.dumps(record))
        self.start()
        self.assertNotEqual(self.server.auth.fingerprint,old)
        self.assertEqual(self.http('session',cookie=cookie)[0],401)
        self.assertEqual(self.http('login',{'username':'admin','password':PASSWORD},origin=self.url)[0],200)

    def test_cli_account_does_not_require_local_service_and_uses_stdin(self):
        token = AccountSettings(self.config, self.directory).bootstrap()
        body = {'setupToken': token, 'username': 'admin', 'password': PASSWORD}
        real_request = request
        with patch('carryon.account_client.request', side_effect=lambda url, action, data=None: real_request(url, action, data, dev_local=True)), \
             patch('carryon.services.running', side_effect=AssertionError('local service not required')), \
             patch('sys.stdin', io.StringIO(json.dumps(body))), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['cloud', 'account', 'setup', '--url', self.url, '--input-json']), 0)
            self.assertNotIn(PASSWORD, output.getvalue()); self.assertNotIn(token, output.getvalue())


class AccountClientTLSTests(unittest.TestCase):
    def test_real_tls_cli_initialization_and_rotation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cert = root/'cert.pem'; key = root/'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                            '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
                            '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
            config = {'publicUrl': 'https://localhost', 'accountSetup': True, 'devices': {}}
            store = AccountSettings(config, root/'state'); token = store.bootstrap()
            server = ConsoleServer(('127.0.0.1', 0), config, root/'state')
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            url = f'https://localhost:{server.server_port}'
            try:
                with self.assertRaises(ValueError):request(url, 'status')
                env = {**os.environ, 'SSL_CERT_FILE': str(cert), 'HTTPS_PROXY': 'http://127.0.0.1:1'}
                def cli(action, data=None):
                    return subprocess.run(['python3', '-m', 'carryon', 'cloud', 'account', action, '--url', url, '--input-json'],
                                          input=json.dumps(data), text=True, capture_output=True, env=env, timeout=30)
                status = cli('status'); self.assertEqual(status.returncode, 0, status.stderr)
                self.assertFalse(json.loads(status.stdout)['configured'])
                initialized = cli('setup', {'setupToken': token, 'username': 'admin', 'password': PASSWORD})
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                changed = cli('change', {'currentUsername': 'admin', 'currentPassword': PASSWORD, 'username': 'owner', 'password': NEW_PASSWORD})
                self.assertEqual(changed.returncode, 0, changed.stderr)
                self.assertNotIn(NEW_PASSWORD, changed.stdout+changed.stderr)
                with patch('carryon.account_client.tls_context', return_value=ssl.create_default_context(cafile=str(cert))):
                    with self.assertRaises(ValueError):request(url.replace('localhost','127.0.0.1'), 'status')
            finally:server.shutdown(); server.server_close(); worker.join(3)
