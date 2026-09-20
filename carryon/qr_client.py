"""Short-lived owner QR invitations shared by desktop and interactive CLI."""
import getpass
import json
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .cloud_wire import endpoint, tls_context
from .http_transport import NoRedirect


def console_request(url, route, data, session=None):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.query or parsed.fragment:raise ValueError('需要准确的云端 HTTPS 地址')
    endpoint('wss://'+parsed.netloc+parsed.path)
    headers={'Content-Type':'application/json','Origin':parsed.scheme+'://'+parsed.netloc}
    if session is not None:
        if not isinstance(session,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',session):raise ValueError('登录会话无效')
        headers['Cookie']='carryon-console='+session
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=tls_context()))
    request=urllib.request.Request(url.rstrip('/')+'/console/'+route,data=json.dumps(data).encode(),headers=headers)
    try:
        with opener.open(request,timeout=15) as response:
            from http.cookies import SimpleCookie
            cookie=SimpleCookie();cookie.load(response.headers.get('Set-Cookie',''))
            raw=response.read(16385)
            if len(raw)>16384:raise ValueError()
            result=json.loads(raw)
            if not isinstance(result,dict):raise ValueError()
            return result,cookie['carryon-console'].value if 'carryon-console' in cookie else session
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError('云端扫码请求失败，请检查登录凭证、云端版本和 public-url') from None
    except (OSError,ValueError):
        raise ValueError('云端扫码请求失败或结果未确认，请核对地址、登录状态或重新生成二维码') from None


def exchange(url, data):
    action=data.get('action')
    if action=='create':
        _, session=console_request(url,'qr/login',{'username':data.get('username'),'password':data.get('password')})
        if not session:raise ValueError('云端未返回登录会话')
        try:
            result,_=console_request(url,'qr/create',{},session)
            key,qr_url=result.get('id'),result.get('url')
            if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}',key) or not isinstance(qr_url,str):raise ValueError('二维码响应无效')
            parsed=urlsplit(qr_url);base=urlsplit(url.rstrip('/')+'/')
            if (parsed.scheme,parsed.netloc,parsed.path)!=(base.scheme,base.netloc,base.path) or parsed.query or not re.fullmatch(r'carryon-login='+re.escape(key)+r'\.[A-Za-z0-9_-]{43}',parsed.fragment):
                raise ValueError('二维码地址与当前云端不一致，请核对服务器 public-url')
            return {'id':key,'url':qr_url,'session':session,'expiresIn':180}
        except BaseException:
            try:console_request(url,'logout',{},session)
            except ValueError:pass
            raise
    if action not in ('status','approve','reject','close'):raise ValueError('扫码操作无效')
    session=data.get('session');key=data.get('id')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}',key):raise ValueError('二维码编号无效')
    if action=='close':
        console_request(url,'logout',{},session)
        return {'closed':True}
    body={'id':key}
    if action=='approve':
        code=data.get('verification')
        if not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code):raise ValueError('请输入手机显示的六位确认码')
        body['verification']=code
    result,_=console_request(url,'qr/'+action,body,session)
    state=result.get('state');code=result.get('verification')
    if state not in ('waiting','scanned','approved','rejected','redeemed') or code is not None and (not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code)):
        raise ValueError('扫码状态无效')
    return {'state':state,'verification':code}


def terminal_qr(value):
    # Reuse the shipped JS encoder through macOS' system JavaScriptCore.
    # No Node/npm/Python QR dependency is required by the distributed CLI.
    import ctypes as c
    from .paths import assets
    if sys.platform!='darwin':raise ValueError('终端二维码目前支持 macOS，请使用云端网页显示二维码')
    js=c.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore')
    signatures={'JSGlobalContextCreate':([c.c_void_p],c.c_void_p),'JSGlobalContextRelease':([c.c_void_p],None),
        'JSStringCreateWithUTF8CString':([c.c_char_p],c.c_void_p),'JSStringRelease':([c.c_void_p],None),
        'JSEvaluateScript':([c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,c.c_int,c.POINTER(c.c_void_p)],c.c_void_p),
        'JSValueToStringCopy':([c.c_void_p,c.c_void_p,c.POINTER(c.c_void_p)],c.c_void_p),
        'JSStringGetMaximumUTF8CStringSize':([c.c_void_p],c.c_size_t),
        'JSStringGetUTF8CString':([c.c_void_p,c.c_char_p,c.c_size_t],c.c_size_t)}
    for name,(args,result) in signatures.items():getattr(js,name).argtypes=args;getattr(js,name).restype=result
    script=(assets()/'qrcode.js').read_text()+'\nvar qr=qrcode(0,"M");qr.addData('+json.dumps(value)+');qr.make();JSON.stringify(Array.from({length:qr.getModuleCount()},(_,r)=>Array.from({length:qr.getModuleCount()},(_,c)=>qr.isDark(r,c))));'
    context=js.JSGlobalContextCreate(None);source=js.JSStringCreateWithUTF8CString(script.encode());text=None
    try:
        error=c.c_void_p();result=js.JSEvaluateScript(context,source,None,None,1,c.byref(error))
        if error.value:raise ValueError('无法生成终端二维码')
        text=js.JSValueToStringCopy(context,result,c.byref(error))
        if error.value or not text:raise ValueError('无法生成终端二维码')
        buffer=c.create_string_buffer(js.JSStringGetMaximumUTF8CStringSize(text))
        js.JSStringGetUTF8CString(text,buffer,len(buffer));matrix=json.loads(buffer.value)
    finally:
        if text:js.JSStringRelease(text)
        js.JSStringRelease(source);js.JSGlobalContextRelease(context)
    width=len(matrix)+8
    rows=[[False]*width]*4+[[False]*4+row+[False]*4 for row in matrix]+[[False]*width]*4
    if len(rows)%2:rows.append([False]*width)
    return '\n'.join(''.join('█' if not top and not bottom else '▀' if not top else '▄' if not bottom else ' '
                            for top,bottom in zip(rows[i],rows[i+1])) for i in range(0,len(rows),2))


def command(args):
    if args.input_json:
        raw=sys.stdin.read(8193)
        try:data=json.loads(raw) if len(raw)<=8192 else None
        except ValueError:data=None
        if not isinstance(data,dict):raise ValueError('扫码输入格式无效')
        print(json.dumps(exchange(args.url,data),ensure_ascii=False));return 0
    if not sys.stdin.isatty():raise ValueError('请在交互终端运行扫码登录')
    username=input('云端账号：').strip();password=getpass.getpass('云端密码（不回显）：')
    invitation=exchange(args.url,{'action':'create','username':username,'password':password});password=None
    try:
        print(terminal_qr(invitation['url']))
        print('请用手机扫码；二维码三分钟内有效。')
        deadline=time.monotonic()+180;decided=False
        while time.monotonic()<deadline:
            state=exchange(args.url,{**invitation,'action':'status'})
            if state['state']=='scanned' and not decided:
                print('手机确认码：'+state['verification'])
                code=input('确认是自己的手机后，输入手机上的六位确认码允许登录；直接回车拒绝：').strip()
                exchange(args.url,{**invitation,'action':'approve' if code else 'reject','verification':code});decided=True
            elif state['state'] in ('redeemed','rejected'):
                print('手机已登录' if state['state']=='redeemed' else '已拒绝登录');return 0
            time.sleep(1.5)
        raise ValueError('二维码已过期，请重新生成')
    except KeyboardInterrupt:
        print('已取消扫码登录')
        return 130
    finally:
        try:exchange(args.url,{**invitation,'action':'close'})
        except ValueError:print('未确认临时登录是否已退出；请在云端核对',file=sys.stderr)
