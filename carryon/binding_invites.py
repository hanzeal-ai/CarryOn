"""Account-confirmed workstation binding. Scan and polling secrets are distinct."""
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from .paths import save_json
from .workspace_access import permissions


class BindingInvites:
    def __init__(self, server, directory):
        import json
        self.server = server
        self.lock = threading.RLock()
        self.path = Path(directory)/'binding-invites.json' if directory else None
        self.entries = json.loads(self.path.read_text()) if self.path and self.path.exists() else {}
        self.starts = {}

    def throttle(self, peer):
        with self.lock:
            now = time.monotonic()
            self.starts = {key:[t for t in values if t > now-60] for key,values in self.starts.items() if any(t > now-60 for t in values)}
            attempts = self.starts.setdefault(peer, [])
            if len(attempts) >= 6: raise PermissionError('此来源连接申请过于频繁，请一分钟后重试')
            if len(self.starts) > 1024: raise PermissionError('连接申请过多，请稍后重试')
            attempts.append(now)

    def bind_known(self, data):
        from .member_management import device_record
        with self.lock, self.server.lock:
            _, source = device_record(self.server, data.get('source', {}))
            identity = data.get('accountId')
            if identity not in source.get('members', {'owner':['view']}): raise PermissionError('账号尚未在此电脑确认')
            key = self.digest(data.get('requestId'))
            for ident, entry in self.entries.items():
                if entry.get('knownRequest') == key and entry.get('knownSource') == data['source']['deviceId']:
                    if entry.get('account') != identity or entry['permissions'] != permissions(data.get('permissions')):
                        raise ValueError('初始化请求参数已改变')
                    record = self.server.config['devices'].get(entry.get('deviceId'))
                    if record is None: raise PermissionError('授权结果未确认或已撤销，请核对工作区')
                    return {'state':'bound','deviceId':entry['deviceId'],'token':record['deviceToken'], 'account':self.server.auth.profile(identity)}
            self.entries = {k:v for k,v in self.entries.items()
                            if not v.get('knownRequest') or v.get('knownSource') in self.server.config['devices']}
            if sum(bool(v.get('knownRequest')) for v in self.entries.values()) >= 1024:
                raise ValueError('初始化历史已达上限，请核对已有工作区；不会重复创建')
            result = self.start(data)
            ident, scan = result['url'].split('#carryon-bind=')[1].split('.')
            self.entries[ident].update(knownRequest=key, knownSource=data['source']['deviceId'])
            self.save()
            self.accept({'id':ident, 'secret':scan}, identity)
            return self.poll({'id':ident,'secret':result['secret']})

    def save(self):
        if self.path:
            save_json(self.path, self.entries)

    def start(self, data):
        name = data.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('工作区名称无效')
        allowed = permissions(data.get('permissions'))
        if 'view' not in allowed: raise ValueError('请选择查看工作区权限')
        with self.lock:
            self.entries = {k:v for k,v in self.entries.items() if v['expires'] > time.time() or v.get('knownRequest')}
            if sum(v['expires'] > time.time() and v['state'] not in ('bound', 'cancelled') for v in self.entries.values()) >= 64:
                raise ValueError('连接请求过多，请稍后重试')
            ident, poll, scan = secrets.token_urlsafe(24), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.entries[ident] = {'name': name.strip(), 'permissions': allowed,
                                  'poll': self.digest(poll), 'scan': self.digest(scan),
                                  'expires': time.time()+300, 'state': 'waiting'}
            self.save()
            return {'id': ident, 'secret': poll, 'expiresAt': self.entries[ident]['expires'],
                    'url': self.server.public_url+'/#carryon-bind='+ident+'.'+scan}

    @staticmethod
    def digest(value):
        if not isinstance(value, str) or not 32 <= len(value) <= 128:
            raise PermissionError('邀请凭证无效')
        return hashlib.sha256(value.encode()).hexdigest()

    def entry(self, data, kind):
        ident = data.get('id')
        if not isinstance(ident, str): raise ValueError('邀请编号无效')
        record = self.entries.get(ident)
        if record is None or record['expires'] <= time.time(): raise ValueError('二维码已过期，请在电脑端重新生成')
        if not secrets.compare_digest(self.digest(data.get('secret')), record[kind]):
            raise PermissionError('邀请凭证无效')
        if kind == 'scan' and record['state'] == 'cancelled':
            raise ValueError('二维码已取消，请在电脑端重新生成')
        return record

    def cancel(self, data):
        with self.lock:
            entry = self.entry(data, 'poll')
            if entry.get('account') or entry.get('deviceId') or entry['state'] in ('accepted', 'bound'):
                raise ValueError('手机已确认绑定，请先完成当前绑定')
            previous = entry['state']
            entry['state'] = 'cancelled'
            try:
                self.save()
                if self.path:
                    fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                    try:os.fsync(fd)
                    finally:os.close(fd)
            except OSError:
                # A failed directory sync can follow a visible atomic rename.
                if self.path and self.path.exists():
                    self.entries = json.loads(self.path.read_text())
                else:
                    entry['state'] = previous
                raise
            return {'state':'cancelled'}

    def inspect(self, data, identity):
        with self.lock:
            entry = self.entry(data, 'scan')
            if entry.get('account') not in (None, identity): raise PermissionError('邀请已由其他账号确认')
            return {'name': entry['name'], 'permissions': entry['permissions'], 'state': entry['state'],
                    'account': self.server.auth.profile(identity)}

    def accept(self, data, identity):
        with self.lock, self.server.lock:
            entry = self.entry(data, 'scan')
            if entry.get('account') not in (None, identity): raise PermissionError('邀请已由其他账号确认')
            if entry.get('workspaceId'):
                if entry['workspaceId'] not in self.server.config['devices']: raise PermissionError('工作区已撤销')
                if entry['state'] != 'bound':
                    entry.update(account=identity, state='accepted')
                    self.save()
                return {'state':entry['state'], 'deviceId':entry['workspaceId']}
            device = entry.get('deviceId')
            if device is None:
                # Save intent before device registration; retries use the same ID.
                device = secrets.token_hex(16)
                entry.update(account=identity, deviceId=device)
                self.save()
            existing = self.server.config['devices'].get(device)
            if entry['state'] == 'bound' and existing is None:
                raise PermissionError('工作区已撤销，请重新生成邀请')
            if existing is None:
                if len(self.server.config['devices']) >= 256: raise ValueError('工作区数量已达上限')
                record = {'name': entry['name'], 'deviceToken': secrets.token_urlsafe(32),
                          'apiToken': secrets.token_urlsafe(32), 'ownerUserId': identity,
                          'members': {identity: entry['permissions']}}
                self.server.save_devices({**self.server.config['devices'], device: record})
            entry['state'] = 'bound'
            self.save()
            return {'state': 'bound', 'deviceId': device}

    def poll(self, data):
        with self.lock, self.server.lock:
            entry = self.entry(data, 'poll')
            if entry.get('workspaceId'):
                if entry['workspaceId'] not in self.server.config['devices']: raise PermissionError('工作区已撤销')
                return {'state':entry['state'], 'account': self.server.auth.profile(entry['account']) if entry.get('account') else None}
            if entry['state'] != 'bound': return {'state': entry['state']}
            device = entry['deviceId']
            record = self.server.config['devices'].get(device)
            if record is None: raise PermissionError('工作区已撤销')
            return {'state': 'bound', 'deviceId': device, 'token': record['deviceToken'],
                    'permissions': entry['permissions'], 'account': self.server.auth.profile(entry['account'])}
