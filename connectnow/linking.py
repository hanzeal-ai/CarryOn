"""Short-lived device authorization; poll secrets never enter the browser."""
import math
import json
from pathlib import Path
from .paths import save_json
import hashlib
import secrets
import threading
import time


class LinkRequests:
    HISTORY_LIMIT = 1000
    def __init__(self, history_path=None):
        self.lock = threading.RLock()
        self.entries = {}
        self.starts = []
        self.history_path = Path(history_path) if history_path else None
        self.history = []
        self.history_error = None
        try:
            if self.history_path and self.history_path.exists():
                values = json.loads(self.history_path.read_text())
                if not isinstance(values, list): raise ValueError('历史格式无效')
                self.history = [self.history_record(value) for value in values[:self.HISTORY_LIMIT]]
        except (OSError, ValueError, TypeError, KeyError):
            self.history_error = '历史文件无法读取，新的申请仍可正常处理'

    @staticmethod
    def history_record(value):
        if not isinstance(value, dict): raise ValueError('历史记录无效')
        if any(not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 100 for key in ('id', 'name')):
            raise ValueError('历史记录标识无效')
        if value.get('result') not in ('approved', 'rejected', 'expired'): raise ValueError('历史结果无效')
        if any(isinstance(value.get(key), bool) or not isinstance(value.get(key), (int, float)) or not math.isfinite(value[key]) for key in ('created', 'resolvedAt')):
            raise ValueError('历史时间无效')
        return {key: value[key] for key in ('id', 'name', 'created', 'result', 'resolvedAt')}

    def archive(self, key, entry, result):
        if entry['name'] is None: return
        self.history.insert(0, {'id': key, 'name': entry['name'], 'created': entry['created'],
                                'result': result, 'resolvedAt': time.time()})
        del self.history[self.HISTORY_LIMIT:]
        # History is a display projection; a disk failure must not change an authorization outcome.
        try:
            if self.history_path: save_json(self.history_path, self.history)
            self.history_error = None
        except OSError:
            self.history_error = '历史记录暂未保存到磁盘，请检查云端存储'

    def history_snapshot(self):
        with self.lock:
            self.prune()
            return [self.history_record(item) for item in self.history]

    def clear_history(self):
        with self.lock:
            self.prune()
            if self.history_path: save_json(self.history_path, [])
            self.history = []
            self.history_error = None


    def prune(self):
        now = time.monotonic()
        for key, entry in self.entries.items():
            if entry['expires'] <= now and entry['device'] is None and not entry['rejected']:
                self.archive(key, entry, 'expired')
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
            self.archive(key, entry, 'approved')

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
            if entry['device'] is not None or entry['rejected']:raise ValueError('连接申请已处理')
            entry['rejected']=True
            self.archive(key, entry, 'rejected')
