"""Reference cloud gateway. Put behind TLS and your existing account backend."""
import argparse
import hmac
import json
import os
import secrets
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from . import __version__
from .cloud import PROTOCOL, ID
from .paths import save_json
from .websocket import WebSocket, upgrade


class Offline(Exception):pass
class Uncertain(Exception):pass


class Device:
    def __init__(self,ws):
        self.ws=ws;self.closed=False;self.lock=threading.Condition()
        self.pending={};self.streams={}

    def call(self,message,timeout=25):
        mid=uuid.uuid4().hex;entry={'event':threading.Event()}
        with self.lock:
            if self.closed:raise Offline()
            if len(self.pending)>=32:raise ValueError('设备请求过多')
            self.pending[mid]=entry
        try:
            self.ws.send({**message,'id':mid})
            if not entry['event'].wait(timeout):raise Uncertain()
            if 'response' not in entry:raise Uncertain()
            return entry['response']
        except OSError as exc:raise Uncertain() from exc
        finally:
            with self.lock:self.pending.pop(mid,None)

    def receive(self,message):
        with self.lock:
            if message.get('type')=='response':
                entry=self.pending.get(message.get('id'))
                if entry:
                    status=message.get('status')
                    if type(status) is not int or not 100<=status<=599:raise ValueError('Invalid response')
                    entry['response']=message;entry['event'].set()
            elif message.get('type')=='event':
                stream=self.streams.get(message.get('streamId'))
                if stream:
                    stream['revision']+=1;stream['body']=message.get('body');self.lock.notify_all()
            elif message.get('type')!='pong':raise ValueError('Invalid device message')

    def close(self):
        with self.lock:
            self.closed=True;self.streams.clear()
            for entry in self.pending.values():entry['event'].set()
            self.lock.notify_all()


class Gateway(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,config,handler=None):
        super().__init__(address,handler or Handler)
        self.config=config;self.devices={};self.lock=threading.RLock()
        self.release=os.environ.get("CONNECTNOW_RELEASE","development")
        self.slots=threading.BoundedSemaphore(64)


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*_):pass
    def reply(self,status,data):
        # Some authorization/offline failures precede body parsing. Never reuse
        # a connection whose unread request body could become the next request.
        self.close_connection=True
        payload=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Connection','close');self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(payload)
    def body(self):
        if self.headers.get('Transfer-Encoding'):raise ValueError('不支持 Transfer-Encoding')
        size=int(self.headers.get('Content-Length','0'))
        from .images import MAX_REQUEST_BYTES
        limit=MAX_REQUEST_BYTES if urlsplit(self.path).path.endswith('/request') else 100000
        if not 0<size<=limit or self.headers.get_content_type()!='application/json':raise ValueError('JSON 请求体无效')
        body=json.loads(self.rfile.read(size))
        if not isinstance(body,dict):raise ValueError('需要 JSON 对象')
        return body
    def authorized(self,device_id):
        record=self.server.config['devices'].get(device_id)
        token=self.headers.get('Authorization','')
        return bool(record and hmac.compare_digest(token,'Bearer '+record['apiToken']))
    def do_GET(self):self.handle_api('GET')
    def do_POST(self):self.handle_api('POST')
    def do_DELETE(self):self.handle_api('DELETE')
    def do_OPTIONS(self):self.reply(403,{'error':'请通过自己的后端接入，不向浏览器开放设备凭证'})

    def handle_api(self,method):
        try:
            self.connection.settimeout(30)
            parsed=urlsplit(self.path);parts=parsed.path.strip('/').split('/')
            if parsed.path=='/healthz' and method=='GET':
                self.reply(200,{'service':'connectnow-gateway','version':__version__,'release':self.server.release});return
            if parsed.path=='/device' and method=='GET':
                if self.headers.get('Origin'):self.reply(403,{'error':'Device endpoint is not for browsers'});return
                if not self.server.slots.acquire(False):self.reply(503,{'error':'连接过多'});return
                try:upgrade(self);self.device_socket()
                finally:self.server.slots.release()
                return
            if len(parts)<3 or parts[:2]!=['v1','devices']:
                self.reply(404,{'error':'Not found'});return
            device_id=parts[2]
            if not self.authorized(device_id):self.reply(401,{'error':'设备访问未授权'});return
            if self.headers.get('Origin'):
                self.reply(403,{'error':'API Token 仅供自有云端后端使用'});return
            with self.server.lock:device=self.server.devices.get(device_id)
            if len(parts)==3 and method=='GET':
                self.reply(200,{'deviceId':device_id,'online':bool(device and not device.closed)});return
            if not device or device.closed:raise Offline()
            if parts[3:]==['request'] and method=='POST':
                data=self.body()
                response=device.call({'type':'request','method':data.get('method'),
                    'path':data.get('path'),'body':data.get('body')})
                self.reply(response['status'],response.get('body'));return
            if parts[3:]==['streams'] and method=='POST':
                selection=self.body();sid=uuid.uuid4().hex
                with device.lock:
                    if len(device.streams)>=8:raise ValueError('最多 8 个订阅，请释放不再使用的订阅')
                    device.streams[sid]={'revision':0,'body':None}
                try:response=device.call({'type':'subscribe','streamId':sid,'selection':selection})
                except BaseException:
                    with device.lock:device.streams.pop(sid,None)
                    raise
                if response['status']!=200:
                    with device.lock:device.streams.pop(sid,None)
                self.reply(response['status'],response.get('body'));return
            if len(parts)==5 and parts[3]=='streams':
                sid=parts[4]
                with device.lock:
                    if sid not in device.streams:self.reply(404,{'error':'订阅不存在或已断线失效'});return
                if method=='DELETE':
                    response=device.call({'type':'unsubscribe','streamId':sid})
                    with device.lock:device.streams.pop(sid,None)
                    self.reply(response['status'],response.get('body'));return
                if method=='GET':
                    after=int(parse_qs(parsed.query).get('after',['-1'])[0])
                    deadline=time.monotonic()+20
                    with device.lock:
                        while not device.closed and sid in device.streams and device.streams[sid]['revision']<=after:
                            remaining=deadline-time.monotonic()
                            if remaining<=0:break
                            device.lock.wait(remaining)
                        if device.closed:raise Offline()
                        record=device.streams.get(sid)
                        if record is None:self.reply(404,{'error':'订阅已关闭'});return
                        result=dict(record)
                    self.reply(200,result);return
            self.reply(404,{'error':'Not found'})
        except Offline:self.reply(503,{'error':'设备离线；未排队投递'})
        except Uncertain:self.reply(409,{'error':'设备响应未确认；使用原 requestId 查询，不要自动重发','uncertain':True})
        except (ValueError,TypeError,KeyError):self.reply(400,{'error':'请求参数或协议无效'})
        except (OSError,EOFError):pass

    def device_socket(self):
        ws=WebSocket(self)
        device=None;device_id=None;closed=threading.Event()
        def heartbeat():
            while not closed.wait(15):
                try:ws.send({'type':'ping','id':uuid.uuid4().hex})
                except OSError:return
        try:
            self.connection.settimeout(5)
            hello=ws.receive();device_id=hello.get('deviceId')
            if not isinstance(device_id,str) or not ID.fullmatch(device_id):raise ValueError('deviceId invalid')
            record=self.server.config['devices'].get(device_id)
            if (hello.get('type')!='hello' or hello.get('protocol')!=PROTOCOL or not record
                or not isinstance(hello.get('token'),str) or not hmac.compare_digest(hello['token'],record['deviceToken'])):
                ws.send({'type':'rejected'});return
            ws.MAX_MESSAGE=32*1024*1024
            device=Device(ws)
            with self.server.lock:
                current=self.server.config['devices'].get(device_id)
                if current is None or not hmac.compare_digest(hello['token'],current['deviceToken']):
                    ws.send({'type':'rejected'});return
                if device_id in self.server.devices:
                    ws.send({'type':'rejected','error':'设备已有连接'});return
                self.server.devices[device_id]=device
            self.connection.settimeout(45)
            ws.send({'type':'ready','protocol':PROTOCOL,'deviceId':device_id})
            threading.Thread(target=heartbeat,daemon=True).start()
            while True:device.receive(ws.receive())
        except (OSError,EOFError,ValueError,TypeError,KeyError):pass
        finally:
            closed.set()
            if device:
                device.close()
                with self.server.lock:
                    if self.server.devices.get(device_id) is device:self.server.devices.pop(device_id,None)


def main():
    parser=argparse.ArgumentParser(description='ConnectNow 自托管参考网关（置于 TLS 反向代理后）')
    parser.add_argument('action',choices=['init','serve'])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--device-id',default='my-mac')
    parser.add_argument('--port',type=int,default=8780)
    args=parser.parse_args()
    if args.action=='init':
        paths=[args.config,args.config.parent/'device-token.txt',args.config.parent/'api-token.txt']
        if any(p.exists() or p.is_symlink() for p in paths):parser.error('配置或凭证已存在，拒绝覆盖')
        if not ID.fullmatch(args.device_id):parser.error('device-id 无效')
        device_token=secrets.token_urlsafe(32);api_token=secrets.token_urlsafe(32)
        args.config.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        payloads=[json.dumps({'devices':{args.device_id:{'deviceToken':device_token,'apiToken':api_token}}}),device_token,api_token]
        for path,payload in zip(paths,payloads):
            with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:stream.write(payload)
        print('已生成网关配置、device-token.txt 和 api-token.txt；分别交给设备与自有后端。')
    else:
        config=json.loads(args.config.read_text())
        server=Gateway(('127.0.0.1',args.port),config)
        print(f'Gateway: http://127.0.0.1:{server.server_port}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()


if __name__=='__main__':main()
