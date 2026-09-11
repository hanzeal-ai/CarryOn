"""Short-lived device authorization; poll secrets never enter the browser."""
import hashlib
import secrets
import threading
import time


class LinkRequests:
    def __init__(self):
        self.lock = threading.RLock()
        self.entries = {}

    def prune(self):
        now = time.monotonic()
        self.entries = {k:v for k,v in self.entries.items() if v['expires'] > now}

    def start(self):
        with self.lock:
            self.prune()
            if len(self.entries) >= 64: raise ValueError('连接请求过多，请稍后重试')
            key, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            verification = secrets.token_hex(3).upper()
            self.entries[key] = {'secret':hashlib.sha256(secret.encode()).digest(), 'expires':time.monotonic()+300,
                                 'verification':verification, 'device':None}
            return {'id':key, 'secret':secret, 'verification':verification}

    def get(self, key):
        self.prune()
        if not isinstance(key,str) or key not in self.entries: raise ValueError('连接请求不存在或已过期')
        return self.entries[key]

    def approve(self, key, device):
        with self.lock:
            entry = self.get(key)
            if entry['device'] is not None: raise ValueError('连接请求已处理')
            entry['device'] = device

    def poll(self, key, secret):
        with self.lock:
            entry = self.get(key)
            if not isinstance(secret,str) or not secrets.compare_digest(entry['secret'],hashlib.sha256(secret.encode()).digest()):
                raise PermissionError('连接请求凭证无效')
            device = entry['device']
            if device is not None: del self.entries[key]
            return device
