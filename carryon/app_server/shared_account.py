"""Borrow native credentials without sharing a workspace's persistent state.

Codex owns credential storage (including Keychain) and token renewal. Only an
access token crosses the local stdio boundary; workspace auth is ephemeral.
"""
import base64
import hashlib
import json
import threading
from contextlib import suppress

from carryon.errors import IPCError
from carryon.paths import default_codex_home


def source_home():
    from carryon.services import records
    from pathlib import Path
    desktop = next((row for row in records().values()
                    if not row.get('removed') and row.get('backend', 'desktop-ipc') == 'desktop-ipc'
                    and row.get('codexHome')), None)
    return Path(desktop['codexHome']).resolve() if desktop else default_codex_home()


def account_home(bridge):
    return source_home() if getattr(bridge, 'backend', None) == 'app-server' else bridge.catalog.home


class SharedAccount:
    def __init__(self, client):
        self.client = client
        self.lock = threading.RLock()
        self.fingerprint = None
        self.stopped = threading.Event()
        self.login_reader = None

    def start_login(self):
        from carryon.app_server.app_server import AppServer
        from carryon.paths import private_dir
        with self.lock:
            if self.stopped.is_set():
                raise IPCError('工作区已停止')
            if self.login_reader is None or not self.login_reader.connected:
                self.login_reader = AppServer(private_dir(source_home()),
                    runtime_directory=self.client.runtime_directory / 'account-login')
                self.login_reader.connect()
            return self.login_reader.rpc('account/login/start', {'type': 'chatgpt'})

    def close(self):
        self.stopped.set()
        with self.lock:
            if self.login_reader is not None:
                self.login_reader.close()
                self.login_reader = None

    def read(self, refresh=False):
        from carryon.app_server.initialization import initialization_lock
        from carryon.paths import private_dir
        from carryon.services import catalog_directory
        # Serialize forced renewal across CarryOn processes without queuing
        # ordinary reads from every workspace behind network token renewal.
        if refresh:
            with initialization_lock(private_dir(catalog_directory() / 'account-sync'), timeout=2):
                return self._read(True)
        return self._read(False)

    def _read(self, refresh=False):
        from carryon.app_server.app_server import AppServer
        home = source_home()
        if home == self.client.home:
            raise IPCError('共享登录来源不能是当前独立工作区')
        if not home.is_dir():
            return None
        # A fresh native reader observes file/Keychain login, logout and account
        # changes instead of retaining another process's cached credentials.
        reader = AppServer(home, runtime_directory=self.client.runtime_directory / 'account-source')
        try:
            reader.connect()
            auth = reader.rpc('getAuthStatus', {'includeToken': True, 'refreshToken': refresh}, timeout_ms=7000)
            if not isinstance(auth, dict):
                raise ValueError('invalid native auth response')
            token = auth.get('authToken')
            if token is None and auth.get('authMethod') is None:
                return None
            if not isinstance(token, str) or not token:
                raise ValueError('invalid native auth token')
            if auth.get('authMethod') == 'apikey':
                return {'type': 'apiKey', 'apiKey': token}
            if auth.get('authMethod') != 'chatgpt':
                raise ValueError('unsupported native auth mode')
            payload = token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            if not isinstance(claims, dict):
                raise ValueError('invalid native claims')
            identity = claims['https://api.openai.com/auth']
            if not isinstance(identity, dict):
                raise ValueError('invalid native identity')
            # Newer native releases expose the selected workspace routing.
            # Older releases only expose this identity in the access token.
            routing = reader.initial_account.get('workspaceRouting')
            if routing is not None and not isinstance(routing, dict):
                raise ValueError('invalid native workspace routing')
            account_id = routing['chatgptAccountId'] if routing is not None else identity['chatgpt_account_id']
            if not isinstance(account_id, str) or not account_id:
                raise ValueError('missing account identity')
            if identity.get('chatgpt_plan_type') is not None and not isinstance(identity['chatgpt_plan_type'], str):
                raise ValueError('invalid native plan')
            return {'type': 'chatgptAuthTokens', 'accessToken': token,
                    'chatgptAccountId': account_id,
                    'chatgptPlanType': identity.get('chatgpt_plan_type')}
        except (IPCError, OSError, ValueError, KeyError, IndexError, TypeError):
            # Never forward a native auth error or token contents to logs/UI.
            raise IPCError('无法读取本机 Codex 登录状态，请检查本机 Codex 登录后重试') from None
        finally:
            reader.close()

    def sync(self):
        with self.lock:
            if self.stopped.is_set():
                raise IPCError('工作区已停止')
            try:
                credentials = self.read()
                fingerprint = hashlib.sha256(json.dumps(credentials, sort_keys=True).encode()).digest() if credentials else None
                if credentials and fingerprint != self.fingerprint:
                    self.client.rpc('account/login/start', credentials)
                elif not credentials and self.fingerprint is not None:
                    self.client.rpc('account/logout', {})
                self.fingerprint = fingerprint
                self.client.account_ready = credentials is not None
                if credentials and self.login_reader and self.login_reader.account_ready:
                    self.login_reader.close()
                    self.login_reader = None
            except (IPCError, OSError, ValueError):
                self.client.account_ready = False
                self.fingerprint = None
                with suppress(IPCError, OSError):
                    self.client.rpc('account/logout', {})
                raise IPCError('无法同步本机 Codex 登录状态，请检查本机 Codex 登录后重试') from None
        self.client.on_change()

    def watch(self):
        while not self.stopped.wait(30):
            if not self.client.connected:
                return
            with suppress(IPCError, OSError):
                self.sync()

    def refresh(self, event, process):
        failed = False
        try:
            with self.lock:
                credentials = self.read(refresh=True)
                previous = event.get('params', {}).get('previousAccountId')
                if not credentials or credentials['type'] != 'chatgptAuthTokens' or (
                        previous and credentials['chatgptAccountId'] != previous):
                    raise IPCError('本机 Codex 账号已退出或改变，请重新发起任务')
                result = {key: value for key, value in credentials.items() if key != 'type'}
                response = {'id': event['id'], 'result': result}
        except (IPCError, OSError, ValueError):
            failed = True
            response = {'id': event['id'], 'error': {'code': -32000,
                        'message': '无法刷新本机 Codex 登录，请检查本机账号后重试'}}
        # A response from a previous child must never enter a replacement child.
        with self.client.lock:
            if self.client.process is process and self.client.connected:
                if failed:
                    self.client.account_ready = False
                with suppress(IPCError, OSError):
                    self.client._write(response)
