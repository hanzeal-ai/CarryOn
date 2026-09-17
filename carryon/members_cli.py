"""CLI and desktop facade over authenticated native membership management."""
import json
import sys
import time

from .onboarding import request


def binding(directory, ident=None):
    from .cloud_manager import CloudManager
    bindings = CloudManager.saved_bindings(directory)
    if ident is None and len(bindings) == 1: ident = next(iter(bindings))
    if ident not in bindings: raise ValueError('请选择已绑定的云端工作区')
    config = bindings[ident]
    url = config['url']
    if not url.startswith('wss://') or not url.endswith('/device'): raise ValueError('此云端不支持账号成员管理')
    return 'https'+url[3:-7], {'deviceId':config['deviceId'],'token':config['token']}


def exchange(directory, data):
    url, credentials = binding(directory, data.get('bindingId'))
    if data.get('action') == 'known-accounts':
        from .onboarding import known_accounts
        return known_accounts(url)
    body = {k:v for k,v in data.items() if k not in ('bindingId','sourceDirectory','sourceBindingId')}
    if data.get('sourceDirectory'):
        source_url, source = binding(data['sourceDirectory'], data.get('sourceBindingId'))
        if source_url != url: raise ValueError('已有账号必须来自同一云端')
        body['source'] = source
    return request(url, 'manage', {**body, **credentials})


def command(args):
    if args.input_json:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192: raise ValueError('成员输入过长')
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError('成员输入无效')
        print(json.dumps(exchange(args.state_dir, data), ensure_ascii=False)); return 0
    data = {'action':args.action, 'bindingId':args.binding_id, 'accountId':args.account_id,
            'permissions':args.permissions.split(',') if args.permissions else ['view'],
            'sourceDirectory':str(args.source_state_dir) if args.source_state_dir else None}
    if args.action == 'invite' and not sys.stdin.isatty(): raise ValueError('请在交互终端邀请使用者')
    result = exchange(args.state_dir, data)
    if args.action != 'invite':
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    from .qr_client import terminal_qr
    print(terminal_qr(result['url']))
    print('请使用者登录自己的 CarryOn 账号后扫码接受邀请。')
    url, _ = binding(args.state_dir, args.binding_id)
    while time.time() < result['expiresAt']:
        state = request(url, 'poll', {'id':result['id'],'secret':result['secret']})
        if state['state'] == 'accepted':
            account = state['account']
            print('使用者账号：'+account['username']+'（'+account['id']+'）')
            if input('核对账号后授予所选权限？[y/N]：').strip().lower() != 'y':
                print('未授予权限；邀请到期后失效。'); return 0
            exchange(args.state_dir, {'action':'confirm','bindingId':args.binding_id,
                     'id':result['id'],'secret':result['secret'],'accountId':account['id']})
            print('工作区权限已授予。'); return 0
        time.sleep(1.5)
    raise ValueError('邀请已过期，未新增授权')
