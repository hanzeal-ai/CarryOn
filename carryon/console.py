"""Single-owner example console embedding the device gateway in its backend."""
import argparse
import hashlib
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
from .console_auth import ConsoleAuth, SESSION_SECONDS, password_record
from .account_settings import AccountSettings


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
        self.account_settings=AccountSettings(config,state_dir)
        self.auth=ConsoleAuth(self.account_settings.effective(),state_dir)
        parsed=urlsplit(self.public_url)
        self.origin=parsed.scheme+'://'+parsed.netloc
        self.prefix=parsed.path.rstrip('/')
        self.sessions=self.auth.load_sessions();self.console_streams={};self.auth_lock=threading.RLock()
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
        from .binding_invites import BindingInvites
        self.binding_invites = BindingInvites(self, state_dir)
        self.push=None
        if config.get('apns'):
            if state_dir is None:raise ValueError('APNs 需要持久化 state-dir')
            from .apns import APNsSender
            from .push import PushService
            self.push=PushService(self,Path(state_dir)/'push.sqlite',APNsSender(config['apns']))

    def replace_auth(self, config):
        updated=ConsoleAuth(config,self.account_settings.directory)
        if updated.fingerprint == self.auth.fingerprint:return
        updated.attempts=self.auth.attempts
        self.auth=updated
        # Persisted sessions are bound to the old authority and cannot restore.
        self.sessions={}
        for sid in list(self.console_streams):self.release_stream(sid)

    def account_request(self, action, data):
        with self.auth_lock, self.account_settings.locked():
            self.replace_auth(self.account_settings.effective())
            if action=='invite':
                token = data.get('issuerToken')
                expected = self.config.get('registrationInviteIssuerHash', '')
                if (not isinstance(token, str) or not 32 <= len(token) <= 128
                    or not isinstance(expected, str) or len(expected) != 64
                    or not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)):
                    raise PermissionError('此电脑未获授权生成邀请码')
                return self.auth.create_registration_invite()
            if action=='status':
                return {'configured':self.auth.account is not None}
            username = data.get('username')
            if isinstance(username, str) and any(record['username'].casefold() == username.strip().casefold() for record in self.auth.users.values()):
                raise ValueError('账号已存在，请使用其他管理员账号名称')
            try:
                if action=='setup':
                    self.auth.throttle()
                    self.account_settings.initialize(data)
                else:
                    if self.auth.account is None:raise PermissionError('请先设置管理员账号')
                    if self.auth.verify({'username':data.get('currentUsername'),'password':data.get('currentPassword')}) != 'owner':
                        raise PermissionError('需要管理员凭证')
                    self.account_settings.change(data)
            finally:
                # A directory fsync can fail after rename: reflect any visible commit,
                # revoke old sessions, and still report an uncertain result to the caller.
                self.replace_auth(self.account_settings.effective())
            return {'configured':True,'changed':True}

    def change_password(self, key, data):
        with self.auth_lock:
            identity = self.auth.identity(key)
            username = self.auth.profile(identity)['username']
            if self.auth.verify({'username':username, 'password':data.get('currentPassword')}) != identity:
                raise PermissionError('当前密码不正确')
            record = password_record(username, data.get('password'))
            if identity == 'owner':
                self.account_request('change', {'currentUsername':username, 'currentPassword':data.get('currentPassword'),
                                               'username':username, 'password':data.get('password')})
            else:
                users = {**self.auth.users, identity:record}
                if self.auth.users_path: save_json(self.auth.users_path, users)
                self.auth.users = users
                revoked = {session for session in self.sessions if self.auth.identity(session) == identity}
                for stream, value in list(self.console_streams.items()):
                    if value['session'] in revoked: self.release_stream(stream)
                for session in revoked:
                    self.sessions.pop(session, None)
                    self.auth.identities.pop(session, None)
                self.auth.save_sessions(self.sessions)
            return {'changed':True}

    def server_close(self):
        if getattr(self,'push',None):self.push.close()
        super().server_close()

    def save_devices(self,records):
        if self.registry_path:save_json(self.registry_path,records)
        self.config['devices']=records

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
        for sid in streams:self.release_stream(sid)
        if self.push:self.push.revoke(device)

    def prune(self):
        now=time.monotonic()
        self.sessions={k:v for k,v in self.sessions.items() if v>now}
        self.auth.prune(self.sessions)


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
    def body(self):
        cached = getattr(self, 'forward_body', None)
        return cached if cached is not None else super().body()

    def reply(self,status,data):
        access = getattr(self, 'access_context', None)
        if access and 200 <= status < 300:
            from .workspace_access import require
            try:
                with self.server.auth_lock, self.server.lock:
                    require(self.server, *access)
            except PermissionError:
                context = getattr(self, 'stream_context', None)
                if context and isinstance(data, dict) and data.get('streamId'):
                    sid = data['streamId']
                    with self.server.auth_lock:
                        self.server.console_streams[sid] = {'device':context[0], 'session':context[1], 'last':time.monotonic()}
                    self.server.release_stream(sid)
                if getattr(self, 'forwarded_write', False):
                    status, data = 409, {'error':'授权已变更；请求可能已经执行，请在电脑核对原 requestId，勿重新提交。', 'uncertain':True}
                else:
                    status, data = 403, {'error':'工作区授权已变更，请刷新'}
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
            token=cookies['carryon-console'].value
        except (KeyError,ValueError,CookieError):return None
        key=hashlib.sha256(token.encode()).hexdigest()
        with self.server.auth_lock:
            self.server.prune()
            return key if key in self.server.sessions else None

    def set_session_cookie(self,token,lifetime=SESSION_SECONDS):
        self.cookie='carryon-console='+token+'; HttpOnly; SameSite=Strict; Path='+self.server.prefix+'/console/; Max-Age='+str(lifetime)+('; Secure' if self.server.origin.startswith('https:') else '')

    def issue_session(self,lifetime=SESSION_SECONDS,identity='owner'):
        self.server.prune()
        if len(self.server.sessions)>=64:raise ValueError('登录会话过多，请退出其他设备后重试')
        token=secrets.token_urlsafe(32)
        self.server.auth.identities[hashlib.sha256(token.encode()).hexdigest()] = identity
        sessions={**self.server.sessions,hashlib.sha256(token.encode()).hexdigest():time.monotonic()+lifetime}
        self.server.auth.save_sessions(sessions)
        self.server.sessions=sessions
        self.set_session_cookie(token,lifetime)
        return token

    def check_origin(self,method):
        origin=self.headers.get('Origin')
        if (origin is not None and origin!=self.server.origin
            or method!='GET' and origin!=self.server.origin):
            raise PermissionError('控制台请求来源不匹配')

    def static(self,path):
        name=path.lstrip('/') or 'example.html'
        allowed={'logo.svg','favicon.png','apple-touch-icon.png','example.html','style.css','shadcn.css','shadcn-ui.js','mobile.css','mobile-ui.js','app.js','subagents.js','notification-client.js','workspace-binding.js','client.js',
                 'cloud-console-client.js','console-mode.js','operations.js','timeline.js','console-login.js','qrcode.js'}
        if name not in allowed:return False
        payload=b'window.CARRYON_CLOUD=true;' if name=='console-mode.js' else (assets()/name).read_bytes()
        if name=='example.html':
            text=payload.decode().replace('href="/','href="'+self.server.prefix+'/').replace('src="/','src="'+self.server.prefix+'/')
            text=text.replace('</head>','<script src="'+self.server.prefix+'/console-mode.js"></script></head>')
            text=text.replace('CarryOn · Codex 本地桥接','CarryOn · 云端控制台')
            payload=text.encode()
        self.send_response(200)
        self.send_header('Content-Type',mimetypes.guess_type(name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        socket_origin = self.server.origin.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
        self.send_header('Content-Security-Policy',f"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' {socket_origin}; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers();self.wfile.write(payload);return True

    def handle_api(self,method):
        self.cookie=None;self.stream_context=None
        self.connection.settimeout(30)
        path=urlsplit(self.path).path
        try:
            if method=='GET' and self.static(path):return
            if not path.startswith('/console/'):
                return super().handle_api(method)
            if path in ('/console/account','/console/account/setup','/console/account/change','/console/account/invite'):
                # Native administration uses a setup code, current password, or issuer credential;
                # browser cookies and workspace device tokens cannot authorize it.
                if self.headers.get('Origin'):raise PermissionError('请在桌面端或 CLI 管理云端账号')
                action='status' if path=='/console/account' else path.rsplit('/',1)[-1]
                if method != ('GET' if action=='status' else 'POST'):
                    self.reply(405,{'error':'请求方法无效'});return
                data={} if action=='status' else self.body()
                if not isinstance(data,dict):raise ValueError('账号参数无效')
                try:result=self.server.account_request(action,data)
                except PermissionError:raise
                except OSError:
                    self.reply(503,{'error':'无法确认云端账号设置结果，请检查存储状态并核对登录'});return
                self.reply(200,result);return
            if path == '/console/binding/manage' and method == 'POST':
                if self.headers.get('Origin'): raise PermissionError('请在电脑端管理授权')
                from .member_management import manage
                self.reply(200, manage(self.server, self.body())); return
            if path in ('/console/binding/start', '/console/binding/poll', '/console/binding/cancel') and method == 'POST':
                if self.headers.get('Origin'): raise PermissionError('请在电脑端发起绑定')
                if path.endswith('/start'): self.server.binding_invites.throttle(self.client_address[0])
                action = {'start':self.server.binding_invites.start, 'poll':self.server.binding_invites.poll, 'cancel':self.server.binding_invites.cancel}[path.rsplit('/',1)[-1]]
                self.reply(200, action(self.body())); return
            self.check_origin(method)
            if path == '/console/register' and method == 'POST':
                data = self.body()
                with self.server.auth_lock:
                    try:identity = self.server.auth.register(data)
                    except ValueError as exc:
                        self.reply(400, {'error':str(exc)});return
                    except OSError:
                        self.reply(503, {'error':'无法确认注册结果，请先尝试登录；请勿重复提交'});return
                    self.issue_session(identity=identity)
                self.reply(200, {'authenticated': True}); return
            if path in ('/console/login','/console/qr/login') and method=='POST':
                data=self.body()
                with self.server.auth_lock:
                    identity = self.server.auth.verify(data)
                    self.issue_session(300 if path=='/console/qr/login' else SESSION_SECONDS, identity)
                self.reply(200,{'authenticated':True});return
            if path in ('/console/qr/claim','/console/qr/poll') and method=='POST':
                data=self.body()
                with self.server.auth_lock:
                    self.server.prune()
                    if path.endswith('/claim'):
                        self.reply(200,self.server.auth.claim(data));return
                    entry=self.server.auth.poll(data)
                    if entry['state']=='approved':
                        entry['token']=self.issue_session(identity=self.server.auth.identity(entry['owner']))
                        entry['state']='redeemed'
                    if entry['state']=='redeemed':
                        if hashlib.sha256(entry['token'].encode()).hexdigest() not in self.server.sessions:
                            raise PermissionError('扫码登录已失效，请重新扫码')
                        self.set_session_cookie(entry['token'])
                        self.reply(200,{'authenticated':True});return
                    self.reply(200,{'state':entry['state']});return
            key=self.session_key()
            if key is None:self.reply(401,{'error':'请先登录云端控制台'});return
            if path == '/console/password' and method == 'POST':
                self.reply(200, self.server.change_password(key, self.body())); return
            if path == '/console/binding/pending' and method == 'GET':
                self.reply(200, self.server.binding_invites.pending(self.server.auth.identity(key))); return
            if path == '/console/binding/respond' and method == 'POST':
                self.reply(200, self.server.binding_invites.accept_target(self.body(), self.server.auth.identity(key))); return
            if path in ('/console/binding/inspect', '/console/binding/accept') and method == 'POST':
                action = self.server.binding_invites.inspect if path.endswith('/inspect') else self.server.binding_invites.accept
                self.reply(200, action(self.body(), self.server.auth.identity(key))); return
            from .workspace_access import granted, require, capability
            if path.startswith('/console/qr/') and method=='POST':
                action=path.rsplit('/',1)[-1];data=self.body()
                with self.server.auth_lock:
                    self.server.prune()
                    if action=='create':result=self.server.auth.create_qr(key,self.server.sessions,self.server.public_url)
                    elif action in ('status','approve','reject'):result=self.server.auth.owner_action(data,key,action)
                    elif action=='cancel':
                        self.server.auth.owner_action(data,key,'status')
                        del self.server.auth.qrs[data['id']];result={'cancelled':True}
                    else:raise ValueError('扫码操作无效')
                self.reply(200,result);return
            if path=='/console/push' and method in ('GET','POST','DELETE'):
                if method=='GET':self.reply(200,{'enabled':self.server.push is not None});return
                if self.server.push is None:self.reply(503,{'error':'服务端尚未配置 APNs'});return
                data=self.body()
                if method=='POST':
                    try:result=self.server.push.register(data,key)
                    except (OSError,EOFError):
                        self.reply(503,{'error':'本机通知服务暂不可用，请稍后重试注册'});return
                else:
                    self.server.push.unregister(data.get('installationId'),key,data.get('revision'));result={'removed':True}
                self.reply(200,result);return
            if path=='/console/logout' and method=='POST':
                data=self.body() if self.headers.get('Transfer-Encoding') or int(self.headers.get('Content-Length','0')) else {}
                with self.server.auth_lock:
                    if self.server.push and data.get('installationId') is not None:
                        self.server.push.unregister(data['installationId'],key,data.get('revision'))
                    remaining={k:v for k,v in self.server.sessions.items() if k!=key}
                    self.server.auth.save_sessions(remaining)
                    self.server.sessions=remaining
                    self.server.prune()
                    if self.server.push:self.server.push.unregister_session(key)
                    owned=[sid for sid,entry in self.server.console_streams.items() if entry['session']==key]
                for sid in owned:self.server.release_stream(sid)
                self.cookie='carryon-console=; HttpOnly; SameSite=Strict; Path='+self.server.prefix+'/console/; Max-Age=0'
                self.reply(200,{'authenticated':False});return
            if path=='/console/session' and method=='GET':
                with self.server.lock:
                    devices=[{'id':d,'name':self.server.config['devices'][d].get('name',d),'online':d in self.server.devices and not self.server.devices[d].closed,
                              'permissions':granted(self.server,key,d)} for d in self.server.config['devices'] if 'view' in granted(self.server,key,d)]
                self.reply(200,{'devices':devices,'publicUrl':self.server.public_url,'account':self.server.auth.profile(self.server.auth.identity(key))});return
            if path.startswith('/console/devices/'):
                parts=path.split('/')
                if len(parts)<4 or not ID.fullmatch(parts[3]) or parts[3] not in self.server.config['devices']:
                    raise PermissionError('设备未授权')
                require(self.server, key, parts[3])
                if len(parts)==4 and method=='DELETE':
                    if self.server.auth.identity(key) != self.server.config['devices'][parts[3]].get('ownerUserId'):
                        raise PermissionError('请在电脑端管理工作区授权')
                    self.server.revoke_device(parts[3]);self.reply(200,{'removed':True,'notice':'设备凭证已撤销；在途请求可能已执行，请在本机核对，勿自动重发'});return
                if len(parts)==5 and parts[4]=='ws' and method=='GET':
                    if self.headers.get('Origin') != self.server.origin:
                        raise PermissionError('实时连接来源不匹配')
                    if urlsplit(self.path).query:
                        raise ValueError('实时连接不接受查询参数')
                    if not self.server.slots.acquire(False):
                        self.reply(503,{'error':'连接过多'});return
                    try:
                        from .websocket import upgrade
                        from .console_socket import serve
                        upgrade(self)
                        serve(self,key,parts[3])
                    finally:self.server.slots.release()
                    return
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
                body = self.body() if method == 'POST' else None
                needed = capability(body.get('method'), body.get('path', ''), body.get('body')) if parts[4:] == ['request'] and body else capability(method, '/api/'+'/'.join(parts[4:]), body)
                require(self.server, key, parts[3], needed)
                self.access_context = (key, parts[3], needed)
                self.activity_owner = self.server.auth.identity(key)
                self.forwarded_write = bool(parts[4:] == ['request'] and body and body.get('method') == 'POST')
                if body is not None:
                    self.forward_body = body
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
    parser=argparse.ArgumentParser(description='example 云端控制台，内置 CarryOn 设备连接')
    parser.add_argument('action',choices=['configure','bootstrap','serve','authorize-inviter'])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--public-url')
    parser.add_argument('--issuer-hash', help='由指定电脑 carryon invate --setup 输出的授权指纹')
    parser.add_argument('--username',help='设置或重设单管理员账号，密码交互输入且不回显')
    parser.add_argument('--state-dir',type=Path,help='可写的设备登记目录，默认配置目录下 console-state')
    parser.add_argument('--port',type=int,default=8780)
    args=parser.parse_args()
    config=json.loads(args.config.read_text()) if args.config.exists() else {'devices':{}}
    if args.action=='serve' and not args.config.exists():parser.error('请先运行 configure 创建控制台配置')
    if args.action=='authorize-inviter':
        if not args.config.exists():parser.error('请先配置云端控制台')
        digest = args.issuer_hash or ''
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            parser.error('需要 --issuer-hash 指定 64 位授权指纹')
        metadata = args.config.stat()
        if os.geteuid() not in (0, metadata.st_uid):raise ValueError('请以配置文件所有者身份运行')
        config['registrationInviteIssuerHash'] = digest
        save_json(args.config, config)
        if os.geteuid() == 0:os.chown(args.config, metadata.st_uid, metadata.st_gid)
        print('已指定唯一的邀请码生成电脑；重启云端控制台后生效。')
        return
    if args.action=='bootstrap':
        if args.config.exists() and args.config.stat().st_uid != os.geteuid():
            parser.error('请以配置文件所有者运行 bootstrap，例如 sudo -u carryon')
        # A new installation needs no publicly usable default credential.
        if not config.get('publicUrl'):
            if not args.public_url:parser.error('首次初始化需要 --public-url')
            config['publicUrl']=public_url(args.public_url)
        if not any(k in config for k in ('account','accountSetup')):
            config['accountSetup']=True
            save_json(args.config,config)
        directory=args.state_dir or args.config.parent/'console-state'
        token=AccountSettings(config,directory).bootstrap()
        print('一次性初始化凭证（10 分钟内有效，重新生成后旧凭证失效）：')
        print(token)
        return
    if args.action=='configure':
        if not args.public_url:parser.error('需要 --public-url')
        config['publicUrl']=public_url(args.public_url)
        if args.username or not any(k in config for k in ('account',)):
            import getpass
            username=args.username or input('管理员账号：').strip()
            password=getpass.getpass('密码（至少 12 位）：')
            if password!=getpass.getpass('再次输入密码：'):raise ValueError('两次密码不一致')
            config['account']=password_record(username,password)
        metadata=args.config.stat() if args.config.exists() else None
        if metadata and os.geteuid() not in (0,metadata.st_uid):raise ValueError('请以配置文件所有者身份运行 configure')
        save_json(args.config,config)
        if metadata and os.geteuid()==0:os.chown(args.config,metadata.st_uid,metadata.st_gid)
        print('云端控制台已配置。'+('账号密码已设置；重启控制台后生效。' if 'account' in config else '请使用 --username 设置账号密码。'));return
    server=ConsoleServer(('127.0.0.1',args.port),config,args.state_dir or args.config.parent/'console-state')
    print('CarryOn example console: '+server.public_url+'/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
