"""Persistent independent cloud bindings sharing one local Bridge."""
import json
import secrets
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .cloud import CloudConnector
from .paths import save_json


class CloudManager:
    validate=staticmethod(CloudConnector.validate)

    def __init__(self,bridge,directory):
        self.bridge=bridge;self.directory=Path(directory);self.path=self.directory/'cloud.json'
        self.lock=threading.RLock();self.connections={}
        data=json.loads(self.path.read_text()) if self.path.exists() else {'version':2,'bindings':{}}
        if 'version' not in data:
            self.validate(data)
            # Preserve an explicit rollback copy before the first format migration.
            backup=self.directory/'cloud-v1-backup.json'
            if not backup.exists():save_json(backup,data)
            data={'version':2,'bindings':{secrets.token_hex(16):data} if data.get('enabled') else {}}
            save_json(self.path,data)
        if data.get('version')!=2 or not isinstance(data.get('bindings'),dict):raise ValueError('云端配置版本无效')
        for key,config in data['bindings'].items():
            if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('绑定 ID 无效')
            self.connections[key]=CloudConnector(bridge,directory,config=config,binding_id=key)

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

    def configure(self,data):
        self.validate(data)
        with self.lock:
            if not data['enabled']:
                key,connection=self._select(data.get('id'))
                connection.stop()
                self.connections.pop(key)
                try:self._save()
                except BaseException:self.connections[key]=connection;connection.start();raise
                return self.status()
            self.check_available(data['url'])
            key=secrets.token_hex(16)
            connection=CloudConnector(self.bridge,self.directory,config=data,binding_id=key)
            self.connections[key]=connection
            try:self._save()
            except BaseException:self.connections.pop(key);raise
            connection.start()
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
