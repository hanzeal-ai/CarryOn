"""Cloud account persistence, bound to the server-managed recovery authority."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import time

from .paths import private_dir, save_json
from .console_auth import password_record

SETUP_SECONDS = 600


def authority(config):
    return {key: config[key] for key in ('account', 'accountSetup') if key in config}


class AccountSettings:
    def __init__(self, config, directory):
        self.config = config
        self.directory = Path(directory) if directory is not None else None
        self.source = hashlib.sha256(json.dumps(authority(config), sort_keys=True).encode()).hexdigest()

    @contextmanager
    def locked(self):
        if self.directory is None:
            raise ValueError('云端需配置持久化 state-dir')
        import fcntl
        private_dir(self.directory)
        with (self.directory / 'account.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        if self.directory is None:
            return {}
        path = self.directory / 'account.json'
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('source'), str):
            raise ValueError('云端账号文件无效，请在服务器恢复配置')
        generation=value.get('generation')
        if generation is not None and (not isinstance(generation,str) or len(generation)!=64 or any(c not in '0123456789abcdef' for c in generation)):
            raise ValueError('云端账号撤销版本无效')
        if value['source'] != self.source:
            return {'generation':generation} if generation else {}
        if 'account' in value and 'setup' in value:
            raise ValueError('云端账号文件无效')
        if 'setup' in value:
            setup = value['setup']
            if (not isinstance(setup, dict) or not isinstance(setup.get('hash'), str)
                or len(setup['hash']) != 64 or not isinstance(setup.get('expires'), (int, float))
                or not math.isfinite(setup['expires'])):
                raise ValueError('初始化凭证记录无效')
        return value

    def effective(self, record=None):
        record = self.read() if record is None else record
        config = dict(self.config)
        if record.get('generation'):config['accountGeneration']=record['generation']
        if 'account' in record:
            config['account'] = record['account']
        return config

    def save(self, record):
        save_json(self.directory / 'account.json', {'version': 1, 'source': self.source, **record})
        # The rename and revocation generation must survive a host crash before success.
        directory_fd=os.open(self.directory,os.O_RDONLY | getattr(os,'O_DIRECTORY',0))
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)

    def bootstrap(self):
        # Used by the server operator only; replacement invalidates the previous code.
        with self.locked():
            if self.effective().get('account') is not None:
                raise ValueError('账号已设置；请验证当前密码修改，或在服务器使用 configure 恢复')
            token = secrets.token_urlsafe(32)
            previous=self.read()
            record={'setup': {'hash': hashlib.sha256(token.encode()).hexdigest(), 'expires': time.time() + SETUP_SECONDS}}
            if previous.get('generation'):record['generation']=previous['generation']
            self.save(record)
            return token

    def initialize(self, data):
        record = self.read()
        if self.effective(record).get('account') is not None:
            raise PermissionError('账号已设置，请使用修改账号密码')
        setup, token = record.get('setup', {}), data.get('setupToken')
        if (not isinstance(token, str) or not 32 <= len(token) <= 128
            or setup.get('expires', 0) <= time.time()
            or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), setup.get('hash', ''))):
            raise PermissionError('初始化凭证无效、已使用或已过期')
        account = password_record(data.get('username'), data.get('password'))
        self.save({'account': account, 'generation': secrets.token_hex(32)})
        return account

    def change(self, data):
        account = password_record(data.get('username'), data.get('password'))
        self.save({'account': account, 'generation': secrets.token_hex(32)})
        return account
