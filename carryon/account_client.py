"""Native desktop/CLI account administration; no stored secrets or request replay."""
import getpass
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .cloud_wire import endpoint, tls_context
from .http_transport import NoRedirect


def request(url, action, data=None, *, dev_local=False):
    if not isinstance(url, str):raise ValueError('需要云端 HTTPS 地址')
    parsed=urlsplit(url)
    if parsed.scheme not in ('https','http'):raise ValueError('需要云端 HTTPS 地址')
    endpoint(('wss' if parsed.scheme=='https' else 'ws')+'://'+parsed.netloc+parsed.path,dev_local)
    if parsed.query or parsed.fragment:raise ValueError('云端地址不能包含查询或片段')
    if action not in ('status','setup','change'):raise ValueError('账号操作无效')
    path='/console/account'+('' if action=='status' else '/'+action)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),
                                      urllib.request.HTTPSHandler(context=tls_context()))
    req=urllib.request.Request(url.rstrip('/')+path,
        data=json.dumps(data).encode() if action!='status' else None,
        headers={'Content-Type':'application/json'})
    try:
        with opener.open(req,timeout=20) as response:
            raw=response.read(8193)
            if len(raw)>8192:raise ValueError('云端账号响应无效')
            result=json.loads(raw)
            if (not isinstance(result,dict) or type(result.get('configured')) is not bool
                or action!='status' and result.get('changed') is not True):
                raise ValueError('云端账号响应无效；请核对登录状态，勿自动重复提交')
            return result
    except urllib.error.HTTPError as exc:
        status=exc.code;exc.close()
        # Do not echo a remote response that could contain submitted secrets.
        if status==404 or action=='status' and status==401:raise ValueError('云端尚未支持账号设置，请先升级云端服务') from None
        if status in (301,302,303,307,308):raise ValueError('云端地址发生重定向，请核对准确地址；凭证未转发') from None
        if status==403:raise ValueError('凭证无效、已过期或尝试过于频繁；请核对后重试') from None
        if status==400:raise ValueError('账号参数无效：账号 1–100 字符，密码 12–256 字符') from None
        raise ValueError('云端未能确认设置结果，请核对登录状态后再操作') from None
    except (OSError, ValueError):
        if action=='status':raise ValueError('无法读取云端账号状态，请检查 HTTPS 地址与网络') from None
        raise ValueError('无法确认云端账号操作结果，请检查地址与网络，并核对登录状态；不会自动重试') from None


def command(args):
    action=args.account_action
    if action=='status':
        result=request(args.url,action)
        print(json.dumps(result,ensure_ascii=False));return 0
    if args.input_json:
        raw=sys.stdin.read(8193)
        if len(raw)>8192:raise ValueError('账号输入过长')
        try:data=json.loads(raw)
        except ValueError:raise ValueError('账号输入格式无效') from None
        if not isinstance(data,dict):raise ValueError('账号输入格式无效')
    else:
        if not sys.stdin.isatty():raise ValueError('请在交互终端输入密码，或通过 --input-json 从标准输入传入')
        data={}
        if action=='setup':data['setupToken']=getpass.getpass('一次性初始化凭证（不回显）：')
        else:
            data['currentUsername']=input('当前账号：').strip()
            data['currentPassword']=getpass.getpass('当前密码（不回显）：')
        data['username']=input('新账号：').strip()
        data['password']=getpass.getpass('新密码（至少 12 位，不回显）：')
        if data['password']!=getpass.getpass('再次输入新密码：'):raise ValueError('两次密码不一致')
    request(args.url,action,data)
    print('云端账号已设置，旧登录已失效。请使用新账号密码登录。')
    return 0
