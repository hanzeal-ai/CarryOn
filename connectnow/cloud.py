"""Opt-in outbound device connector. Remote commands share the local API contract."""
import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from .api import dispatch
from .cloud_wire import connect, close, endpoint
from .errors import BridgeError
from .ipc import IPCError
from .paths import save_json

PROTOCOL='connectnow/1'
ID=re.compile(r'^[A-Za-z0-9_-]{1,100}$')


class CloudConnector:
    def __init__(self,bridge,directory):
        self.bridge=bridge;self.path=Path(directory)/'cloud.json'
        self.lock=threading.RLock();self.config={};self.worker=None;self.ws=None
        self.configure_lock=threading.Lock()
        self.cancel=threading.Event();self.connected=False;self.error=None
        if self.path.exists():
            self.config=json.loads(self.path.read_text())
            self.validate(self.config)

    @staticmethod
    def validate(data):
        if not isinstance(data,dict) or type(data.get('enabled')) is not bool:raise ValueError('enabled 必须为布尔值')
        if not data['enabled']:return
        for name in ('control','devLocal'):
            if type(data.get(name,False)) is not bool:raise ValueError(name+' 必须为布尔值')
        endpoint(data.get('url'),data.get('devLocal',False))
        if not isinstance(data.get('deviceId'),str) or not ID.fullmatch(data['deviceId']):raise ValueError('deviceId 无效')
        if not isinstance(data.get('token'),str) or not 32<=len(data['token'])<=4096:raise ValueError('设备 Token 至少 32 字符')

    def status(self):
        with self.lock:
            return {'enabled':self.config.get('enabled',False),'connected':self.connected,
                'url':self.config.get('url'),'deviceId':self.config.get('deviceId'),
                'control':self.config.get('control',False),'error':self.error,'protocol':PROTOCOL}

    def configure(self,data):
        with self.configure_lock:
            return self._configure(data)

    def _configure(self,data):
        self.validate(data)
        self.stop()
        with self.lock:
            self.config={k:data[k] for k in ('enabled','url','deviceId','token','control','devLocal') if k in data}
            save_json(self.path,self.config)
            self.error=None
        self.start();return self.status()

    def start(self):
        with self.lock:
            if not self.config.get('enabled') or self.worker and self.worker.is_alive():return
            self.cancel=threading.Event()
            self.worker=threading.Thread(target=self.run,args=(dict(self.config),self.cancel),daemon=True)
            self.worker.start()

    def stop(self):
        with self.lock:
            cancel=self.cancel;cancel.set();ws=self.ws;worker=self.worker
            self.connected=False
        if ws:
            try:close(ws)
            except OSError:pass
        if worker and worker is not threading.current_thread():worker.join(12)
        if worker and worker.is_alive():raise ValueError('旧云端连接尚未退出，请稍后重试')
        self.bridge.notify()

    def execute(self,message,control):
        if not isinstance(message.get('id'),str) or not ID.fullmatch(message['id']):raise ValueError('无效消息 ID')
        try:
            status,body=dispatch(self.bridge,message.get('method'),message.get('path'),message.get('body'),remote=True,control=control)
        except BridgeError as exc:status,body=exc.status,{'error':str(exc)}
        except IPCError as exc:status,body=409,{'error':str(exc),'uncertain':exc.uncertain}
        except (ValueError,TypeError,KeyError):status,body=400,{'error':'请求参数无效'}
        except Exception:
            status,body=500,{'error':'本机处理失败；查询原 requestId 核对，勿自动重发','uncertain':True}
        if status==200 and message.get('method')=='GET' and message.get('path')=='/api/status':
            body={**body,'remoteControl':control}
        return {'type':'response','id':message['id'],'status':status,'body':body}

    def session(self,ws,config,cancel):
        streams={}
        def stream_writer(stream_id,subscription,closed):
            revision=-1
            try:
                while not cancel.is_set() and not closed.is_set():
                    revision=subscription.wait(revision)
                    if cancel.is_set() or closed.is_set():break
                    subscription.deliver(subscription.update(),lambda packet:ws.send(
                        {'type':'event','streamId':stream_id,'body':{**packet,'status':{**packet.get('status',{}),'remoteControl':config.get('control',False)}}}))
            except (OSError,ValueError,BridgeError,IPCError):pass
            finally:subscription.close()
        try:
            while not cancel.is_set():
                message=ws.receive()
                if cancel.is_set():break
                kind=message.get('type');mid=message.get('id')
                if not isinstance(mid,str) or not ID.fullmatch(mid):raise ValueError('消息 ID 无效')
                if kind=='ping':ws.send({'type':'pong','id':mid});continue
                if kind=='request':
                    ws.send(self.execute(message,config.get('control',False)));continue
                if kind not in ('subscribe','unsubscribe'):raise ValueError('未知云端消息')
                sid=message.get('streamId')
                if not isinstance(sid,str) or not ID.fullmatch(sid):raise ValueError('streamId 无效')
                if kind=='unsubscribe':
                    entry=streams.pop(sid,None)
                    if entry:entry[1].set();entry[0].close();entry[2].join(2)
                    ws.send({'type':'response','id':mid,'status':200,'body':{'closed':True}});continue
                try:self.bridge.require()
                except BridgeError as exc:
                    ws.send({'type':'response','id':mid,'status':exc.status,'body':{'error':str(exc)}});continue
                if sid not in streams and len(streams)>=8:
                    ws.send({'type':'response','id':mid,'status':429,'body':{'error':'最多 8 个云端订阅'}});continue
                if sid not in streams:
                    sub=self.bridge.open_stream();closed=threading.Event()
                    thread=threading.Thread(target=stream_writer,args=(sid,sub,closed),daemon=True)
                    streams[sid]=(sub,closed,thread)
                sub,closed,thread=streams[sid]
                try:
                    selection=message.get('selection',{})
                    if not isinstance(selection,dict):raise ValueError('Invalid selection')
                    sub.subscribe({**selection,'type':'subscribe','subscription':sid})
                except (ValueError,TypeError) as exc:
                    if thread.ident is None:sub.close();streams.pop(sid,None)
                    ws.send({'type':'response','id':mid,'status':400,'body':{'error':'订阅参数无效'}});continue
                ws.send({'type':'response','id':mid,'status':200,'body':{'streamId':sid}})
                if thread.ident is None:thread.start()
        finally:
            for sub,closed,thread in streams.values():closed.set();sub.close()
            for sub,closed,thread in streams.values():
                if thread.ident is not None:thread.join(2)

    def run(self,config,cancel):
        delay=1
        while not cancel.is_set():
            ws=None
            try:
                ws=connect(config['url'],config.get('devLocal',False))
                with self.lock:
                    if cancel.is_set():break
                    self.ws=ws
                ws.send({'type':'hello','protocol':PROTOCOL,'deviceId':config['deviceId'],'token':config['token']})
                ready=ws.receive()
                if ready.get('type')!='ready' or ready.get('protocol')!=PROTOCOL or ready.get('deviceId')!=config['deviceId']:
                    raise ValueError('云端设备认证或协议不匹配')
                with self.lock:self.connected=True;self.error=None
                delay=1
                self.session(ws,config,cancel)
            except (OSError,EOFError,ValueError,TypeError,KeyError,BridgeError,IPCError,subprocess.SubprocessError) as exc:
                with self.lock:self.error='云端连接中断或协议校验失败：'+type(exc).__name__
            finally:
                with self.lock:self.connected=False;self.ws=None
                if ws:
                    try:close(ws)
                    except OSError:pass
            if cancel.wait(delay):break
            delay=min(30,delay*2)
