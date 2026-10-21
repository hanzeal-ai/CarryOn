"""Owned stdio runtime. Closing this adapter terminates only its own child."""
import fcntl
import json
import os
import subprocess
import threading
import uuid
from contextlib import suppress
from carryon.errors import IPCError
from carryon.paths import private_dir
from carryon.usage import executable
from carryon.app_server.initialization import initialization_lock
from carryon.codex_protocol.client import ProtocolClient


class AppServer(ProtocolClient):
    connection_error_label = '无法启动工作区 app-server：'
    # This private stdio runtime has one client; started threads belong to it.
    started_is_subscribed = True
    def __init__(self, home, *, runtime_directory=None, shared_account=False):
        super().__init__(home, runtime_directory=runtime_directory)
        self.process = None
        self.home_lock = None
        from carryon.app_server.shared_account import SharedAccount
        self.shared_account = SharedAccount(self) if shared_account else None

    def peer(self, *, runtime_directory):
        return AppServer(self.home, runtime_directory=runtime_directory, shared_account=self.shared_account is not None)

    @property
    def connection_identity(self):
        return self.process, self.session_id

    @property
    def connected(self):
        return self.process is not None and self.process.poll() is None

    def connect(self):
        if self.shared_account and self.shared_account.stopped.is_set():
            from carryon.app_server.shared_account import SharedAccount
            self.shared_account = SharedAccount(self)
        self.session_id = uuid.uuid4().hex
        private_dir(self.runtime_directory)
        self.home_lock = (self.runtime_directory / '.carryon-app-server.lock').open('a+')
        try:
            fcntl.flock(self.home_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with initialization_lock(self.home):
                with (self.runtime_directory / 'app-server.log').open('ab') as log:
                    command = [executable(), 'app-server', '--listen', 'stdio://']
                    if self.shared_account:
                        command += ['-c', 'cli_auth_credentials_store="ephemeral"']
                    self.process = subprocess.Popen(command,
                        cwd=str(self.home), env=dict(os.environ, CODEX_HOME=str(self.home)),
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
                threading.Thread(target=self._reader, args=(self.process,), daemon=True, name='app-server-reader').start()
                self.initial_account = self.initialize()
            if self.shared_account:
                self.shared_account.stopped.clear()
                self.shared_account.sync()
                threading.Thread(target=self.shared_account.watch, daemon=True, name='shared-codex-account').start()
        except Exception:
            self.close()
            raise

    def require_account(self):
        if self.shared_account:
            self.shared_account.sync()
            if not self.account_ready:
                raise IPCError('本机 Codex 尚未登录，请在本机 Codex 登录；工作区会自动共享登录状态')
        else:
            super().require_account()

    def _event(self, event):
        if self.shared_account and event.get('method') == 'account/chatgptAuthTokens/refresh' and 'id' in event:
            threading.Thread(target=self.shared_account.refresh, args=(event, self.process),
                             daemon=True, name='shared-codex-refresh').start()
            return
        super()._event(event)

    def _write(self, value):
        payload = json.dumps(value, ensure_ascii=False).encode() + b'\n'
        if len(payload) > self.MAX_FRAME:
            raise IPCError('请求过大')
        with self.write_lock:
            if not self.connected:
                raise IPCError('工作区 app-server 已断开')
            self.process.stdin.write(payload)
            self.process.stdin.flush()

    def _reader(self, process):
        try:
            while True:
                line = process.stdout.readline(self.MAX_FRAME + 1)
                if not line or len(line) > self.MAX_FRAME:
                    break
                value = json.loads(line)
                self.receive(value)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        finally:
            self.close(expected=process)

    def close(self, expected=None):
        with self.lock:
            if expected is not None and self.process is not expected: return
            process, self.process = self.process, None
            home_lock, self.home_lock = self.home_lock, None
            self.disconnected()
        if self.shared_account:
            self.shared_account.close()
        if process:
            if process.poll() is None:
                with suppress(OSError): process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    with suppress(OSError): process.kill()
                    process.wait(timeout=2)
            with suppress(OSError): process.stdin.close()
            with suppress(OSError): process.stdout.close()
        if home_lock: home_lock.close()
        self.on_change()
