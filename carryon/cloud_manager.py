"""Persistent independent cloud bindings sharing one local Bridge."""
import json
import hashlib
import secrets
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .cloud import CloudConnector
from .paths import save_json


class CloudManager:
    validate=staticmethod(CloudConnector.validate)

    @staticmethod
    def saved_bindings(directory):
        """Read and validate current cloud bindings."""
        path = Path(directory)/'cloud.json'
        data = json.loads(path.read_text()) if path.exists() else {'version':2, 'bindings':{}}
        if not isinstance(data, dict):raise ValueError('云端配置版本无效')
        if data.get('version') == 2 and isinstance(data.get('bindings'), dict):
            configs = data['bindings']
            for key in configs:
                if not isinstance(key, str) or len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
                    raise ValueError('绑定 ID 无效')
        else:
            raise ValueError('云端配置版本无效')
        for config in configs.values():CloudConnector.validate(config)
        return configs

    @staticmethod
    def saved_status(directory):
        bindings = [{'id':key, **CloudConnector(None, config=config, binding_id=key).status()}
                    for key, config in CloudManager.saved_bindings(directory).items()]
        return {'enabled':any(c['enabled'] for c in bindings), 'connected':False, 'bindings':bindings}

    def __init__(self,bridge,directory):
        self.bridge=bridge;self.directory=Path(directory);self.path=self.directory/'cloud.json'
        self.lock=threading.RLock();self.connections={}
        for key,config in self.saved_bindings(directory).items():
            self.connections[key]=CloudConnector(bridge,config=config,binding_id=key)

    @staticmethod
    def canonical_url(value):
        parsed=urlsplit(value)
        host=parsed.hostname or ''
        if ':' in host:host='['+host+']'
        port=parsed.port
        authority=host+((':'+str(port)) if port and port!=(443 if parsed.scheme=='wss' else 80) else '')
        return urlunsplit((parsed.scheme.lower(),authority,parsed.path,parsed.query,''))

    def check_available(self,url):
        with self.lock:
            if any(self.canonical_url(c.config['url'])==self.canonical_url(url) for c in self.connections.values()):
                raise ValueError('此云端已绑定，请先解除原绑定')
            if len(self.connections)>=16:raise ValueError('最多连接 16 个云端')

    def _save(self):
        save_json(self.path,{'version':2,'bindings':{k:c.config for k,c in self.connections.items()}})

    def status(self):
        with self.lock:
            bindings=[{'id':k,**c.status()} for k,c in self.connections.items()]
            return {'enabled':any(c['enabled'] for c in bindings),'connected':any(c['connected'] for c in bindings),'bindings':bindings}

    def _select(self,key):
        if key is None and len(self.connections)==1:key=next(iter(self.connections))
        if not isinstance(key,str) or key not in self.connections:raise ValueError('请选择要管理的云端绑定')
        return key,self.connections[key]

    @staticmethod
    def fingerprint(config):
        return hashlib.sha256(json.dumps([config['url'], config['deviceId'], config['token']]).encode()).hexdigest()

    def configure(self,data, *, start=True):
        self.validate(data)
        with self.lock:
            if not data['enabled']:
                key,connection=self._select(data.get('id'))
                connection.stop()
                self.connections.pop(key)
                try:self._save()
                except BaseException:self.connections[key]=connection;connection.start();raise
                return self.status()
            replacement = data.get('replacement')
            config = {key:value for key,value in data.items() if key != 'replacement'}
            if replacement is not None:
                if not isinstance(replacement, dict): raise ValueError('绑定替换参数无效')
                key, previous = self._select(replacement.get('id'))
                if self.canonical_url(previous.config['url']) != self.canonical_url(config['url']):
                    raise ValueError('不能替换其他云端的绑定')
                if self.fingerprint(previous.config) == self.fingerprint(config):
                    if start: previous.start()
                    return self.status()
                if self.fingerprint(previous.config) != replacement.get('fingerprint'):
                    raise ValueError('原绑定已改变，请重新检查绑定状态')
                connection = CloudConnector(self.bridge,config=config,binding_id=key)
                if self.bridge is not None: previous.stop()
                self.connections[key] = connection
                try: self._save()
                except BaseException:
                    self.connections[key] = previous
                    if start: previous.start()
                    raise
                if start: connection.start()
                return self.status()
            self.check_available(data['url'])
            key=secrets.token_hex(16)
            connection=CloudConnector(self.bridge,config=data,binding_id=key)
            self.connections[key]=connection
            try:self._save()
            except BaseException:self.connections.pop(key);raise
            if start: connection.start()
            return self.status()

    def set_control(self,control,key=None):
        if type(control) is not bool:raise ValueError('control 必须为布尔值')
        with self.lock:
            _,connection=self._select(key)
            connection.stop();previous=dict(connection.config)
            connection.config={**previous,'control':control}
            try:self._save()
            except BaseException:connection.config=previous;connection.start();raise
            connection.start();return self.status()

    def start(self):
        with self.lock:
            for connection in self.connections.values():connection.start()

    def stop(self):
        with self.lock:
            for connection in self.connections.values():connection.stop()
