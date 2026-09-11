"""Single-owner example console embedding the device gateway in its backend."""
import argparse
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import json
import mimetypes
import os
from pathlib import Path
import secrets
import re
import threading
import time
from urllib.parse import urlsplit

from .gateway import Gateway, Handler, ID
from .paths import assets, save_json


def public_url(value):
    if not isinstance(value,str) or any(c.isspace() for c in value):raise ValueError('public-url 无效')
    parsed=urlsplit(value)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname
        or parsed.scheme not in ('http','https')
        or parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1')):
        raise ValueError('public-url 必须为 HTTPS；HTTP 仅用于本机测试')
    if not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*/?',parsed.path):raise ValueError('public-url 路径无效')
    return value.rstrip('/')


class ConsoleServer(Gateway):
    """Embeddable transport host; replace console auth with your account backend."""
    def __init__(self,address,config,state_dir=None):
        self.public_url=public_url(config['publicUrl'])
        if not isinstance(config.get('consoleToken'),str) or len(config['consoleToken'])<32:
            raise ValueError('需要独立的 consoleToken（至少32字符）')
        parsed=urlsplit(self.public_url)
        self.origin=parsed.scheme+'://'+parsed.netloc
        self.prefix=parsed.path.rstrip('/')
        from .linking import LinkRequests
        self.links=LinkRequests()
        self.sessions={};self.codes={};self.console_streams={};self.auth_lock=threading.RLock()
        import copy
        config=copy.deepcopy(config)
        self.registry_path=Path(state_dir)/'devices.json' if state_dir is not None else None
        if self.registry_path and self.registry_path.exists():
            records=json.loads(self.registry_path.read_text())
            if not isinstance(records,dict):raise ValueError('设备登记文件无效')
            for device,record in records.items():
                if not ID.fullmatch(device) or not isinstance(record,dict) or any(not isinstance(record.get(k),str) or len(record[k])<32 for k in ('deviceToken','apiToken')):raise ValueError('设备登记文件无效')
            config['devices']=records
        super().__init__(address,config,ConsoleHandler)

    def save_devices(self,records):
        if self.registry_path:save_json(self.registry_path,records)
        self.config['devices']=records

    def approve_link(self,key,device=None):
        with self.links.lock, self.lock:
            entry=self.links.get(key)
            if entry['rejected']:raise ValueError('连接申请已拒绝')
            if entry['name'] is None:
                if not isinstance(device,str) or device not in self.config['devices']:raise PermissionError('设备未授权')
                self.links.approve(key,device)
                return device
            if entry['device'] is not None:return entry['device']
            if len(self.config['devices'])>=256:raise ValueError('最多登记 256 台设备')
            device=secrets.token_hex(16)
            record={'name':entry['name'],'deviceToken':secrets.token_urlsafe(32),'apiToken':secrets.token_urlsafe(32)}
            self.save_devices({**self.config['devices'],device:record})
            self.links.approve(key,device)
            return device

    def revoke_device(self,device):
        import socket
        with self.lock:
            if device not in self.config['devices']:raise ValueError('设备不存在')
            self.save_devices({k:v for k,v in self.config['devices'].items() if k!=device})
            connection=self.devices.pop(device,None)
            if connection:
                connection.close()
                try:connection.ws.handler.connection.shutdown(socket.SHUT_RDWR)
                except (AttributeError,OSError):pass
        with self.auth_lock:
            streams=[sid for sid,e in self.console_streams.items() if e['device']==device]
            self.codes={k:v for k,v in self.codes.items() if v[0]!=device}
        for sid in streams:self.release_stream(sid)

    def prune(self):
        now=time.monotonic()
        self.sessions={k:v for k,v in self.sessions.items() if v>now}
        self.codes={k:v for k,v in self.codes.items() if v[1]>now}


    def release_stream(self,sid):
        with self.auth_lock:entry=self.console_streams.pop(sid,None)
        if entry is None:return
        with self.lock:device=self.devices.get(entry['device'])
        if device is None:return
        with device.lock:device.streams.pop(sid,None);device.lock.notify_all()
        def unsubscribe():
            try:device.call({'type':'unsubscribe','streamId':sid},timeout=5)
            except Exception:pass
        threading.Thread(target=unsubscribe,daemon=True).start()

    def service_actions(self):
        with self.auth_lock:
            self.prune()
            stale=[sid for sid,entry in self.console_streams.items()
                   if entry['session'] not in self.sessions or time.monotonic()-entry['last']>60]
        for sid in stale:self.release_stream(sid)


class ConsoleHandler(Handler):
    def reply(self,status,data):
        # Some authorization/offline failures precede body parsing. Never reuse
        # a connection whose unread request body could become the next request.
        self.close_connection=True
        # Cookie is intentionally scoped to this console prefix, never the shared host root.
        context=getattr(self,'stream_context',None)
        if status==200 and context and isinstance(data,dict) and data.get('streamId'):
            with self.server.auth_lock:
                self.server.console_streams[data['streamId']]={'device':context[0],'session':context[1],'last':time.monotonic()}
        payload=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Connection','close')
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        if getattr(self,'cookie',None):self.send_header('Set-Cookie',self.cookie)
        self.end_headers();self.wfile.write(payload)

    def session_key(self):
        try:
            cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
            token=cookies['connectnow-console'].value
        except (KeyError,ValueError,CookieError):return None
        key=hashlib.sha256(token.encode()).hexdigest()
        with self.server.auth_lock:
            self.server.prune()
            return key if key in self.server.sessions else None

    def check_origin(self,method):
        origin=self.headers.get('Origin')
        if (origin is not None and origin!=self.server.origin
            or method!='GET' and origin!=self.server.origin):
            raise PermissionError('控制台请求来源不匹配')

    def static(self,path):
        name=path.lstrip('/') or 'example.html'
        allowed={'example.html','style.css','app.js','notification-client.js','client.js','cloud-ui.js',
                 'standby-ui.js','cloud-console-client.js','console-mode.js','operations.js','timeline.js'}
        if name not in allowed:return False
        payload=b'window.CONNECTNOW_CLOUD=true;' if name=='console-mode.js' else (assets()/name).read_bytes()
        if name=='example.html':
            text=payload.decode().replace('href="/','href="'+self.server.prefix+'/').replace('src="/','src="'+self.server.prefix+'/')
            text=text.replace('</head>','<script src="'+self.server.prefix+'/console-mode.js"></script></head>')
            text=text.replace('ConnectNow · Codex 本地桥接','ConnectNow · 云端控制台')
            payload=text.encode()
        self.send_response(200)
        self.send_header('Content-Type',mimetypes.guess_type(name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers();self.wfile.write(payload);return True

    def handle_api(self,method):
        self.cookie=None;self.stream_context=None
        self.connection.settimeout(30)
        path=urlsplit(self.path).path
        try:
            if method=='GET' and self.static(path):return
            if not path.startswith('/console/'):
                return super().handle_api(method)
            # Redemption is a CLI exchange protected by a high-entropy single-use code.
            if path=='/console/redeem' and method=='POST':
                if self.headers.get('Origin'):raise PermissionError('请在本机 ConnectNow 完成配对')
                code=self.body().get('code','')
                if not isinstance(code,str):raise ValueError('无效配对码')
                with self.server.auth_lock:
                    self.server.prune();entry=self.server.codes.pop(hashlib.sha256(code.encode()).hexdigest(),None)
                if entry is None:raise PermissionError('配对码无效或已过期')
                device=entry[0]
                self.reply(200,{'deviceId':device,'token':self.server.config['devices'][device]['deviceToken']});return
            if path in ('/console/link/start','/console/link/poll') and method=='POST':
                if self.headers.get('Origin'):raise PermissionError('请在本机发起连接')
                data=self.body()
                if path.endswith('/start'):
                    self.reply(200,self.server.links.start(data.get('name')));return
                device=self.server.links.poll(data.get('id'),data.get('secret'))
                self.reply(200,{'pending':True} if device is None else {'deviceId':device,'token':self.server.config['devices'][device]['deviceToken']});return
            self.check_origin(method)
            if path=='/console/login' and method=='POST':
                token=self.body().get('token','')
                if not isinstance(token,str) or not hmac.compare_digest(token.encode(),self.server.config['consoleToken'].encode()):
                    raise PermissionError('控制台登录凭证无效')
                with self.server.auth_lock:
                    self.server.prune()
                    if len(self.server.sessions)>=64:raise ValueError('登录会话过多，请稍后重试')
                    token=secrets.token_urlsafe(32)
                    self.server.sessions[hashlib.sha256(token.encode()).hexdigest()]=time.monotonic()+12*3600
                self.cookie='connectnow-console='+token+'; HttpOnly; SameSite=Strict; Path='+self.server.prefix+'/console/; Max-Age=43200'+('; Secure' if self.server.origin.startswith('https:') else '')
                self.reply(200,{'authenticated':True});return
            key=self.session_key()
            if key is None:self.reply(401,{'error':'请先登录云端控制台'});return
            if path=='/console/link/inspect' and method=='POST':
                with self.server.links.lock:
                    entry=self.server.links.get(self.body().get('id'))
                    self.reply(200,{'verification':entry['verification']})
                return
            if path=='/console/link/approve' and method=='POST':
                data=self.body()
                device=self.server.approve_link(data.get('id'),data.get('deviceId'))
                self.reply(200,{'approved':True,'deviceId':device});return
            if path=='/console/link/pending' and method=='GET':
                self.reply(200,{'requests':self.server.links.pending()});return
            if path=='/console/link/reject' and method=='POST':
                self.server.links.reject(self.body().get('id'));self.reply(200,{'rejected':True});return
            if path=='/console/logout' and method=='POST':
                with self.server.auth_lock:
                    self.server.sessions.pop(key,None)
                    owned=[sid for sid,entry in self.server.console_streams.items() if entry['session']==key]
                for sid in owned:self.server.release_stream(sid)
                self.cookie='connectnow-console=; HttpOnly; SameSite=Strict; Path='+self.server.prefix+'/console/; Max-Age=0'
                self.reply(200,{'authenticated':False});return
            if path=='/console/session' and method=='GET':
                with self.server.lock:
                    devices=[{'id':d,'name':self.server.config['devices'][d].get('name',d),'online':d in self.server.devices and not self.server.devices[d].closed} for d in self.server.config['devices']]
                self.reply(200,{'devices':devices,'publicUrl':self.server.public_url});return
            if path=='/console/pairing' and method=='POST':
                device=self.body().get('deviceId')
                if not isinstance(device,str) or device not in self.server.config['devices']:raise ValueError('设备不存在')
                code=secrets.token_urlsafe(24)
                with self.server.auth_lock:
                    self.server.prune()
                    if len(self.server.codes)>=64:raise ValueError('配对码过多')
                    self.server.codes[hashlib.sha256(code.encode()).hexdigest()]=(device,time.monotonic()+300)
                self.reply(200,{'code':code,'expiresIn':300,'publicUrl':self.server.public_url});return
            if path.startswith('/console/devices/'):
                parts=path.split('/')
                if len(parts)<4 or not ID.fullmatch(parts[3]) or parts[3] not in self.server.config['devices']:
                    raise PermissionError('设备未授权')
                if len(parts)==4 and method=='DELETE':
                    self.server.revoke_device(parts[3]);self.reply(200,{'removed':True,'notice':'设备凭证已撤销；在途请求可能已执行，请在本机核对，勿自动重发'});return
                if len(parts)==5 and parts[4]=='streams' and method=='POST':self.stream_context=(parts[3],key)
                if len(parts)==6 and parts[4]=='streams':
                    with self.server.auth_lock:
                        entry=self.server.console_streams.get(parts[5])
                        if entry is None:self.reply(404,{'error':'订阅已过期，请重新连接'});return
                        if entry['session']!=key or entry['device']!=parts[3]:raise PermissionError('订阅不属于当前登录会话')
                        entry['last']=time.monotonic()
                    if method=='DELETE':
                        self.server.release_stream(parts[5]);self.reply(200,{'closed':True});return
                # Delegate to the same authoritative gateway routes after console auth.
                original=self.path;headers=self.headers
                from email.message import Message
                forwarded=Message()
                for k,v in headers.items():
                    if k.lower() not in ('authorization','origin'):forwarded[k]=v
                forwarded['Authorization']='Bearer '+self.server.config['devices'][parts[3]]['apiToken']
                self.headers=forwarded;self.path=self.path.replace('/console/devices/','/v1/devices/',1)
                try:return super().handle_api(method)
                finally:self.path=original;self.headers=headers
            self.reply(404,{'error':'接口不存在'})
        except PermissionError as exc:self.reply(403,{'error':str(exc)})
        except (ValueError,KeyError,TypeError):self.reply(400,{'error':'控制台参数无效'})
        except (OSError,EOFError):pass


def main():
    parser=argparse.ArgumentParser(description='example 云端控制台，内置 ConnectNow 设备连接')
    parser.add_argument('action',choices=['configure','serve'])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--public-url')
    parser.add_argument('--state-dir',type=Path,help='可写的设备登记目录，默认配置目录下 console-state')
    parser.add_argument('--port',type=int,default=8780)
    args=parser.parse_args()
    config=json.loads(args.config.read_text()) if args.config.exists() else {'devices':{}}
    if args.action=='serve' and not args.config.exists():parser.error('请先运行 configure 创建控制台配置')
    if args.action=='configure':
        if not args.public_url:parser.error('需要 --public-url')
        config['publicUrl']=public_url(args.public_url)
        if 'consoleToken' not in config:config['consoleToken']=secrets.token_urlsafe(32)
        metadata=args.config.stat() if args.config.exists() else None
        if metadata and os.geteuid() not in (0,metadata.st_uid):raise ValueError('请以配置文件所有者身份运行 configure')
        save_json(args.config,config)
        if metadata and os.geteuid()==0:os.chown(args.config,metadata.st_uid,metadata.st_gid)
        print('云端控制台已配置；consoleToken 保存在配置文件中，不在终端输出。');return
    server=ConsoleServer(('127.0.0.1',args.port),config,args.state_dir or args.config.parent/'console-state')
    print('ConnectNow example console: '+server.public_url+'/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
