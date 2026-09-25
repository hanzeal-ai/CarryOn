"""Single-owner password verification and short-lived, owner-confirmed QR login."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from .paths import private_dir, save_json

SESSION_SECONDS = 30 * 24 * 3600


def password_record(username, password):
    if not isinstance(username, str) or not username.strip() or len(username) > 100:
        raise ValueError('账号须为 1–100 个字符')
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('密码须为 12–256 个字符')
    salt = secrets.token_hex(16)
    return {'username': username.strip(), 'salt': salt,
            'hash': hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()}


class ConsoleAuth:
    # All mutable operations run under ConsoleServer.auth_lock.
    def __init__(self, config, state_dir):
        self.account = config.get('account')
        if self.account is not None:
            a = self.account
            if (not isinstance(a, dict) or not isinstance(a.get('username'), str)
                or not a['username'].strip() or len(a['username']) > 100
                or any(not isinstance(a.get(k), str) for k in ('salt', 'hash'))):
                raise ValueError('账号配置无效')
            try:
                if len(bytes.fromhex(a['salt'])) != 16 or len(bytes.fromhex(a['hash'])) != 64:raise ValueError()
            except ValueError:raise ValueError('账号密码哈希无效') from None
        elif not config.get('accountSetup'):
            raise ValueError('请先 configure --username 设置账号密码')
        authority = self.account
        if config.get('accountGeneration'):authority={'credential':authority,'generation':config['accountGeneration']}
        self.fingerprint = hashlib.sha256(json.dumps(authority, sort_keys=True).encode()).hexdigest()
        self.path = Path(state_dir)/'sessions.json' if state_dir is not None else None
        self.attempts = []
        self.qrs = {}
        self.users_path = Path(state_dir)/'users.json' if state_dir is not None else None
        self.users = json.loads(self.users_path.read_text()) if self.users_path and self.users_path.exists() else {}
        self.identities = {}

    @contextmanager
    def registration_locked(self):
        # Serialize separate ConsoleAuth instances/processes as well as HTTP threads.
        if self.users_path is None:
            raise ValueError('云端需配置持久化 state-dir')
        import fcntl
        private_dir(self.users_path.parent)
        with (self.users_path.parent / 'registration.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.users = json.loads(self.users_path.read_text()) if self.users_path.exists() else {}
            yield

    def save_registration(self, path, data):
        save_json(path, data)
        fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:os.fsync(fd)
        finally:os.close(fd)

    def create_registration_invite(self):
        with self.registration_locked():
            path = self.users_path.parent / 'registration-invites.json'
            invites = json.loads(path.read_text()) if path.exists() else {}
            code = secrets.token_urlsafe(24)
            invites[hashlib.sha256(code.encode()).hexdigest()] = True
            self.save_registration(path, invites)
            return {'inviteCode': code}

    def register(self, data):
        self.throttle()
        if not isinstance(data, dict):
            raise ValueError('注册参数无效')
        code = data.get('inviteCode')
        if not isinstance(code, str) or not 1 <= len(code.strip()) <= 128:
            raise ValueError('请输入邀请码')
        digest = hashlib.sha256(code.strip().encode()).hexdigest()
        with self.registration_locked():
            path = self.users_path.parent / 'registration-invites.json'
            invites = json.loads(path.read_text()) if path.exists() else {}
            if digest not in invites or any(a.get('registrationInviteHash') == digest for a in self.users.values()):
                raise ValueError('邀请码无效或已使用')
            record = password_record(data.get('username'), data.get('password'))
            if (self.account and record['username'].casefold() == self.account['username'].casefold()
                or any(a['username'].casefold() == record['username'].casefold() for a in self.users.values())):
                raise ValueError('账号已存在')
            identity = secrets.token_hex(16)
            # Account creation and consumption commit in the same atomic rename.
            record['registrationInviteHash'] = digest
            users = {**self.users, identity: record}
            try:self.save_registration(self.users_path, users)
            finally:
                # A directory fsync error may follow a visible commit. Never permit reuse.
                self.users = json.loads(self.users_path.read_text()) if self.users_path.exists() else {}
            return identity

    def identity(self, key):
        identity = self.identities.get(key)
        if not isinstance(identity, str) or not (identity == 'owner' and self.account or identity in self.users):
            raise PermissionError('登录身份已失效，请重新登录')
        return identity

    def profile(self, identity):
        record = self.account if identity == 'owner' else self.users.get(identity)
        if not record and identity != 'owner':
            raise PermissionError('账号已失效')
        return {'id': identity, 'username': record['username'] if record else '管理员'}

    def load_sessions(self):
        if self.path is None or not self.path.exists():return {}
        data = json.loads(self.path.read_text())
        if data.get('authority') != self.fingerprint:return {}
        identities = data.get('identities', {})
        self.identities = {key: identity for key, identity in identities.items()
                           if isinstance(identity, str) and (identity == 'owner' and self.account or identity in self.users)} if isinstance(identities, dict) else {}
        now, mono = time.time(), time.monotonic()
        return {key: mono + min(expiry-now, SESSION_SECONDS) for key, expiry in data['sessions'].items()
                if key in self.identities and isinstance(key, str) and len(key) == 64 and isinstance(expiry, (int, float)) and expiry > now}

    def save_sessions(self, sessions):
        if self.path is not None:
            now, mono = time.time(), time.monotonic()
            save_json(self.path, {'authority': self.fingerprint,
                                 'identities': {k: self.identity(k) for k in sessions},
                                 'sessions': {k: now+v-mono for k,v in sessions.items() if v > mono}})

    def throttle(self):
        now = time.monotonic()
        self.attempts = [t for t in self.attempts if t > now-60]
        if len(self.attempts) >= 10:raise PermissionError('尝试过于频繁，请一分钟后重试')
        self.attempts.append(now)

    def verify(self, data):
        self.throttle()
        username, password = data.get('username'), data.get('password')
        if isinstance(username, str) and isinstance(password, str) and len(username) <= 100 and len(password) <= 256:
            for identity, record in self.users.items():
                if record['username'] == username.strip():
                    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record['salt']), n=16384, r=8, p=1)
                    if hmac.compare_digest(digest, bytes.fromhex(record['hash'])):
                        return identity
                    raise PermissionError('账号或密码错误')
        valid = False
        if self.account is not None and isinstance(username, str) and isinstance(password, str) and len(username) <= 100 and len(password) <= 256:
            digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(self.account['salt']), n=16384, r=8, p=1)
            valid = hmac.compare_digest(digest, bytes.fromhex(self.account['hash'])) & hmac.compare_digest(username.strip().encode(), self.account['username'].encode())
        if not valid:raise PermissionError('账号或密码错误' if self.account else '控制台登录凭证无效')
        return 'owner'

    def prune(self, sessions):
        now = time.monotonic()
        self.qrs = {k:v for k,v in self.qrs.items() if v['expires'] > now and v['owner'] in sessions}

    def create_qr(self, owner, sessions, public_url):
        self.prune(sessions)
        # One outstanding invitation per authorizing browser.
        self.qrs = {k:v for k,v in self.qrs.items() if v['owner'] != owner}
        if len(self.qrs) >= 64:raise ValueError('扫码请求过多')
        key, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        self.qrs[key] = {'owner': owner, 'secret': hashlib.sha256(secret.encode()).hexdigest(),
                         'expires': time.monotonic()+180, 'state': 'waiting'}
        return {'id': key, 'url': public_url+'/#carryon-login='+key+'.'+secret, 'expiresIn': 180}

    def entry(self, key):
        if not isinstance(key, str) or key not in self.qrs:raise PermissionError('二维码已过期，请重新生成')
        return self.qrs[key]

    def claim(self, data):
        entry = self.entry(data.get('id'))
        secret = data.get('secret')
        if not isinstance(secret, str) or not hmac.compare_digest(hashlib.sha256(secret.encode()).hexdigest(), entry['secret']):
            raise PermissionError('二维码无效')
        # A client-generated key makes a lost claim response retryable, without letting a second scanner take over.
        claim = data.get('claim')
        if not isinstance(claim, str) or not 32 <= len(claim) <= 128:raise ValueError('扫码请求无效')
        digest = hashlib.sha256(claim.encode()).hexdigest()
        if entry['state'] == 'waiting':
            entry.update(state='scanned', claim=digest, verification=f'{secrets.randbelow(1000000):06d}')
        if not hmac.compare_digest(entry.get('claim', ''), digest):raise PermissionError('二维码已被扫描，请重新生成')
        return {'verification': entry['verification'], 'state': entry['state']}

    def poll(self, data):
        entry = self.entry(data.get('id'))
        claim = data.get('claim')
        if not isinstance(claim, str) or not hmac.compare_digest(hashlib.sha256(claim.encode()).hexdigest(), entry.get('claim', '')):
            raise PermissionError('扫码请求无效')
        return entry

    def owner_action(self, data, owner, action):
        entry = self.entry(data.get('id'))
        if entry['owner'] != owner:raise PermissionError('扫码请求不属于当前登录会话')
        if action in ('approve', 'reject'):
            if entry['state'] != 'scanned':raise ValueError('扫码请求已处理或尚未扫描')
            if action == 'approve' and data.get('verification') != entry['verification']:raise PermissionError('确认码不匹配')
            entry['state'] = 'approved' if action == 'approve' else 'rejected'
        return {'state': entry['state'], 'verification': entry.get('verification')}
