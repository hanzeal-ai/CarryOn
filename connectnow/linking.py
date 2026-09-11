"""Short-lived device authorization; poll secrets never enter the browser."""
import hashlib
import secrets
import threading
import time


class LinkRequests:
    def __init__(self):
        self.lock = threading.RLock()
        self.entries = {}
        self.starts = []

    def prune(self):
        now = time.monotonic()
        self.entries = {k:v for k,v in self.entries.items() if v['expires'] > now}

    def start(self, name=None):
        with self.lock:
            self.prune()
            if name is not None and (not isinstance(name,str) or not name.strip() or len(name)>100):raise ValueError('设备名称无效')
            now=time.monotonic()
            self.starts=[stamp for stamp in self.starts if stamp>now-60]
            if len(self.starts)>=30:raise ValueError('连接申请过于频繁，请稍后重试')
            if len(self.entries) >= 64: raise ValueError('连接请求过多，请稍后重试')
            self.starts.append(now)
            key, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            verification = secrets.token_hex(3).upper()
            self.entries[key] = {'secret':hashlib.sha256(secret.encode()).digest(), 'expires':time.monotonic()+300,
                                 'verification':verification, 'device':None, 'name':name, 'created':time.time(), 'rejected':False}
            return {'id':key, 'secret':secret, 'verification':verification}

    def get(self, key):
        self.prune()
        if not isinstance(key,str) or key not in self.entries: raise ValueError('连接请求不存在或已过期')
        return self.entries[key]

    def approve(self, key, device):
        with self.lock:
            entry = self.get(key)
            if entry['device'] is not None or entry['rejected']: raise ValueError('连接请求已处理')
            entry['device'] = device

    def poll(self, key, secret):
        with self.lock:
            entry = self.get(key)
            if not isinstance(secret,str) or not secrets.compare_digest(entry['secret'],hashlib.sha256(secret.encode()).digest()):
                raise PermissionError('连接请求凭证无效')
            device = entry['device']
            if entry['rejected']:raise PermissionError('连接申请已拒绝')
            if device is not None and entry['name'] is None: del self.entries[key]
            return device

    def pending(self):
        with self.lock:
            self.prune()
            return [{'id':key,'name':entry['name'],'verification':entry['verification'],'created':entry['created']}
                    for key,entry in self.entries.items() if entry['name'] is not None and entry['device'] is None and not entry['rejected']]

    def reject(self,key):
        with self.lock:
            entry=self.get(key)
            if entry['device'] is not None:raise ValueError('连接申请已处理')
            entry['rejected']=True
