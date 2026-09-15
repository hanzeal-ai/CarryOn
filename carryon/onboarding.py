"""Shared, resumable CLI/desktop initialization without a temporary bridge service."""
import contextlib
import fcntl
import io
import json
import secrets
import socket
import time
import urllib.request
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from .paths import default_codex_home, private_dir, save_json
from .pairing import NoRedirect
from .cloud_wire import endpoint, tls_context


class InvalidDeviceCredentials(ValueError):
    pass


def request(url, action, body):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment:
        raise ValueError('请输入完整的 HTTPS 云端地址')
    endpoint('wss://'+parsed.netloc+parsed.path.rstrip('/')+'/device')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=tls_context()))
    req = urllib.request.Request(url.rstrip('/')+'/console/binding/'+action,
                                 data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    try:
        with opener.open(req, timeout=20) as response:
            raw = response.read(16385)
            if len(raw) > 16384: raise ValueError('绑定响应过长')
            value = json.loads(raw)
            if not isinstance(value, dict): raise ValueError('绑定响应无效')
            return value
    except urllib.error.HTTPError as error:
        try:
            raw = error.read(16385)
            value = json.loads(raw) if len(raw) <= 16384 else None
            detail = value.get('error') if isinstance(value, dict) else None
        except (OSError, ValueError):
            detail = None
        finally:
            error.close()
        if error.code == 403 and detail == '设备凭证无效':
            raise InvalidDeviceCredentials('设备凭证无效，请重新绑定此云端工作区后再试') from None
        raise ValueError(f'云端请求失败（HTTP {error.code}）' + (f'：{detail[:500]}' if isinstance(detail, str) else '')) from None


def install_binding(directory, config, replacement=None):
    from .cli import running, call
    from .cloud_manager import CloudManager
    from .cloud import CloudConnector
    CloudConnector.validate(config)
    if replacement: config = {**config, 'replacement':replacement}
    with (directory/'launcher.lock').open('a+') as launcher:
        fcntl.flock(launcher, fcntl.LOCK_EX)
        if running(directory):
            if not replacement:
                status = call(directory, '/cloud')
                if any(row.get('deviceId') == config['deviceId'] and row.get('url') == config['url'] for row in status['bindings']): return
            call(directory, '/cloud', config, timeout=20)
        else:
            with (directory/'server.lock').open('a+') as service:
                try: fcntl.flock(service, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: raise ValueError('服务正在启动，请稍后继续初始化') from None
                manager = CloudManager(None, directory)
                if not replacement and any(manager.fingerprint(c.config) == manager.fingerprint(config) for c in manager.connections.values()): return
                manager.configure(config, start=False)


def exchange(directory, data):
    from .services import register, records
    from .cli import running, call, start
    if not isinstance(data, dict): raise ValueError('初始化输入无效')
    directory = private_dir(directory)
    with (directory/'init.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory/'onboarding.json'
        state = json.loads(path.read_text()) if path.exists() else {'state':'new'}
        action = data.get('action', 'status')
        if action not in ('status', 'prepare', 'poll', 'known-accounts', 'apply-confirmed'): raise ValueError('初始化操作无效')
        if state.get('pending') and not state['pending'].get('confirmed') and state['pending']['expiresAt'] <= time.time():
            state.pop('pending'); state['state'] = 'configured'; save_json(path, state)
            if action == 'poll': raise ValueError('二维码已过期，配置已保留，请继续初始化')
        if state.get('pending') and data.get('bindingId') and data['bindingId'] != state.get('replacement', {}).get('id'):
            raise ValueError('另一项绑定正在进行，请先完成或等待二维码过期')
        if action != 'known-accounts' and not state.get('pending'):
            from .binding_recovery import reconcile
            state, verification_error = reconcile(directory, state, data)
            if verification_error:
                if action != 'status': raise ValueError(verification_error)
                return exchange_ready(directory, {**state, 'state':'unverified', 'error':verification_error}, 'status')
            save_json(path, state)
            if state['state'] == 'bound' and str(directory) not in records():
                info = running(directory)
                register(directory, port=info['port'] if info else 0,
                         codex_home=info['codexHome'] if info else default_codex_home())
        if action == 'known-accounts':
            return known_accounts(data.get('url', ''))
        if action not in ('status', 'prepare', 'poll', 'apply-confirmed'): raise ValueError('初始化操作无效')
        if action == 'apply-confirmed':
            confirmed = state.get('pending', {}).get('confirmed')
            replacement = state.get('replacement')
            if not confirmed or not replacement: raise ValueError('没有待应用的扫码结果')
            # This explicit desktop/CLI action is separate from automatic polling.
            verified = request(state['url'], 'manage', {'action':'list', 'deviceId':confirmed['deviceId'], 'token':confirmed['token']})
            if not isinstance(verified.get('members'), list): raise ValueError('绑定验证响应无效')
            from .cloud_manager import CloudManager
            manager = CloudManager(None, directory)
            _, current = manager._select(replacement['id'])
            if manager.canonical_url(current.config['url']) != manager.canonical_url('wss'+state['url'][5:]+'/device'):
                raise ValueError('不能替换其他云端的绑定')
            state['replacement'] = {'id':replacement['id'], 'fingerprint':manager.fingerprint(current.config)}
            save_json(path, state)
            action = 'poll'
        if action == 'prepare' and state.get('pending', {}).get('confirmed'):
            action = 'poll'
        if action == 'prepare' and state['state'] != 'bound':
            url = data.get('url', state.get('url', ''))
            if not isinstance(url, str): raise ValueError('云端地址无效')
            auto = data.get('autoStart', state.get('autoStart', True))
            control = data.get('control', False)
            if type(auto) is not bool or type(control) is not bool: raise ValueError('初始化选项无效')
            from .workspace_access import CAPABILITIES, permissions
            allowed = permissions(data.get('permissions', list(CAPABILITIES) if control else ['view','files']))
            if 'view' not in allowed: raise ValueError('请选择查看工作区权限')
            control = bool(set(allowed)-{'view','files'})
            if state.get('pending') and state['pending']['expiresAt'] > time.time():
                if url.rstrip('/') != state['url'] or auto != state['autoStart'] or control != state['control'] or allowed != state.get('permissions',allowed):
                    raise ValueError('绑定正在进行，请完成或等待二维码过期后调整选项')
            else:
                saved = records().get(str(directory), {})
                name = data.get('name', saved.get('name', socket.gethostname()))
                codex = Path(data.get('codexHome', saved.get('codexHome', str(default_codex_home())))).expanduser().resolve()
                port = data.get('port', saved.get('port', 0))
                register(directory, name=name, port=port, codex_home=codex)
                request_id = state.get('requestId', secrets.token_hex(16))
                replacement = state.get('replacement')
                if replacement and url.rstrip('/') != state.get('url'):
                    raise ValueError('重新绑定时不能更改云端地址')
                state = {'state':'configured', 'url':url.rstrip('/'), 'autoStart':auto, 'name':name, 'requestId':request_id, 'control':control,'permissions':allowed}
                if replacement: state['replacement'] = replacement
                save_json(path, state)
                from .workspace_access import CAPABILITIES
                if data.get('sourceDirectory'):
                    from .members_cli import binding
                    source_url, source = binding(data['sourceDirectory'], data.get('sourceBindingId'))
                    if source_url != state['url']: raise ValueError('账号必须来自同一云端')
                    result = request(state['url'], 'known', {'name':name,'permissions':allowed,
                        'source':source,'accountId':data.get('accountId'),'requestId':request_id})
                    install_binding(directory, {'enabled':True,'url':'wss'+state['url'][5:]+'/device',
                        'deviceId':result.get('deviceId'),'token':result.get('token'),'control':control}, state.get('replacement'))
                    state.update(state='bound', account=result.get('account'),deviceId=result['deviceId']); save_json(path,state)
                    return exchange_ready(directory, state, action)
                pending = request(state['url'], 'start', {'name':name, 'permissions':allowed})
                if not all(isinstance(pending.get(k), str) for k in ('id','secret','url')) or not isinstance(pending.get('expiresAt'), (float,int)):
                    raise ValueError('绑定响应无效')
                if not pending['url'].startswith(state['url']+'/#carryon-bind='): raise ValueError('绑定地址与当前云端不一致')
                state.update(state='waiting', pending=pending, control=control)
                save_json(path, state)
        if action == 'poll' and state.get('pending'):
            pending = state['pending']
            result = pending.get('confirmed') or request(state['url'], 'poll', {'id':pending['id'], 'secret':pending['secret']})
            if result.get('state') == 'bound':
                config = {'enabled':True,'url':'wss'+state['url'][5:]+'/device',
                          'deviceId':result.get('deviceId'),'token':result.get('token'),'control':state['control']}
                from .cloud import CloudConnector
                CloudConnector.validate(config)
                pending['confirmed'] = result
                state['state'] = 'confirming'
                save_json(path, state)
                try:
                    install_binding(directory, config, state.get('replacement'))
                except (OSError, ValueError) as error:
                    state['error'] = '扫码结果已保存，尚未应用：'+str(error)
                    save_json(path, state)
                    return exchange_ready(directory, state, 'status')
                state.update(state='bound', account=result.get('account'), deviceId=result['deviceId'])
                state.pop('pending'); state.pop('error', None); save_json(path, state)
        return exchange_ready(directory, state, action)


def exchange_ready(directory, state, action):
    from .cli import running, call, start
    from .services import records
    import sys
    saved = records().get(str(directory), {})
    codex = Path(saved.get('codexHome', default_codex_home()))
    if action in ('prepare','poll') and state['state'] == 'bound' and state.get('autoStart', True):
        saved = records()[str(directory)]
        with contextlib.redirect_stdout(io.StringIO()):
            start(SimpleNamespace(state_dir=directory, port=saved['port'], codex_home=Path(saved['codexHome']), no_open=True))
    info = running(directory)
    bridge = call(directory, '/status') if info else {}
    cloud = call(directory, '/cloud') if info else {}
    return {k:v for k,v in {**state, 'pending':None,
            'environment': {'supportedPlatform':sys.platform == 'darwin', 'codexHome':str(codex),
                            'ipcAvailable':(codex/'ipc/ipc.sock').exists(), 'databaseAvailable':any(codex.glob('state_*.sqlite'))},
            'confirmedAccount':state.get('pending', {}).get('confirmed', {}).get('account'),
            'qrURL':None if state.get('pending', {}).get('confirmed') else state.get('pending', {}).get('url'), 'running':bool(info),
            'bridgeConnected':bool(bridge.get('enabled')), 'cloudConnected':bool(cloud.get('connected'))}.items() if k not in ('pending', 'replacement')}

def known_accounts(url):
    from .services import records
    from .members_cli import binding, exchange as members
    if not isinstance(url, str): raise ValueError('云端地址无效')
    result, warnings = {}, []
    for directory in records():
        path = Path(directory)/'cloud.json'
        if not path.exists(): continue
        stored = json.loads(path.read_text())
        for ident in stored.get('bindings', {}):
            if stored['bindings'][ident].get('url') != 'wss'+url.rstrip('/')[5:]+'/device': continue
            source_url, _ = binding(directory, ident)
            if source_url != url.rstrip('/'): continue
            try:
                values = members(directory, {'action':'list','bindingId':ident})
            except (OSError, ValueError):
                warnings.append('一个已有工作区的账号暂不可用，可继续扫码绑定。')
                continue
            for row in values['members']:
                account = row['account']
                result.setdefault(account['id'], {**account,'sourceDirectory':directory,'sourceBindingId':ident})
    return {'accounts':list(result.values()), 'warnings':list(dict.fromkeys(warnings))}


def command(args):
    import sys
    from .qr_client import terminal_qr
    if args.input_json:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192: raise ValueError('初始化输入过长')
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError('初始化输入无效')
        print(json.dumps(exchange(args.state_dir, data), ensure_ascii=False)); return 0
    if not sys.stdin.isatty(): raise ValueError('请在交互终端执行 init，或通过 --input-json 输入配置')
    state = exchange(args.state_dir, {'action':'status'})
    if not state['environment']['supportedPlatform']: raise ValueError('当前 CLI 桥接仅支持 macOS')
    if not state['environment']['ipcAvailable']:
        print('尚未发现运行中的 Codex App；可以先绑定，启动服务后将等待 Codex。')
    if state['state'] != 'bound':
        if state['state'] != 'waiting':
            url = args.url or input('云端 HTTPS 地址'+(' ['+state['url']+']' if state.get('url') else '')+'：').strip() or state.get('url','')
            auto = input('绑定完成后自动启动服务？[Y/n]：').strip().lower() != 'n'
            control = input('允许在手机上操作会话（发送、停止、编辑和审批）？[y/N]：').strip().lower() == 'y'
            known = known_accounts(url)
            accounts = known['accounts']
            for warning in known['warnings']: print(warning)
            selected = {}
            if accounts:
                print('0. 使用其他账号扫码绑定')
                for index, account in enumerate(accounts, 1): print(str(index)+'. '+account['username'])
                choice = input('选择已确认账号，或回车扫码：').strip()
                if choice and choice != '0':
                    if not choice.isdecimal() or not 1 <= int(choice) <= len(accounts): raise ValueError('账号选择无效')
                    selected = accounts[int(choice)-1]
            state = exchange(args.state_dir, {'action':'prepare','url':url,'autoStart':auto,'control':control,
                **({'permissions':args.permissions.split(',')} if args.permissions else {}),
                **({'accountId':selected['id'],'sourceDirectory':selected['sourceDirectory'],'sourceBindingId':selected['sourceBindingId']} if selected else {})})
        if state.get('qrURL'):
            print(terminal_qr(state['qrURL']))
            print('请在已登录的 CarryOn App 中扫码，核对工作区及权限后确认。')
    try:
        while state['state'] != 'bound':
            time.sleep(1.5)
            state = exchange(args.state_dir, {'action':'poll'})
        state = exchange(args.state_dir, {'action':'poll'})
    except KeyboardInterrupt:
        print('已暂停初始化，配置已保留；再次执行 carryon init 可继续。'); return 130
    print('绑定已保存。')
    if not state.get('autoStart', True): print('执行 carryon start 启动桥接。')
    elif state['bridgeConnected'] and state['cloudConnected']: print('工作区已就绪，可在手机上使用。')
    else: print('服务已启动，正在等待 Codex 或云端连接；使用 carryon status 查看状态。')
    return 0
