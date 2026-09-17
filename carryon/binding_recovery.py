"""Reconcile saved bindings against the cloud before reusing or replacing credentials."""
from .cloud_manager import CloudManager


def reconcile(directory, state, data):
    from .onboarding import request, InvalidDeviceCredentials
    bindings = CloudManager.saved_bindings(directory)
    active = {key:value for key,value in bindings.items() if value.get('enabled')}
    target = data.get('bindingId')
    if target is not None and target not in active:
        raise ValueError('请选择已保存的云端绑定')
    requested = data.get('url')
    if requested is not None:
        from .cloud_wire import endpoint
        from urllib.parse import urlsplit
        if not isinstance(requested, str):raise ValueError('云端地址无效')
        parsed = urlsplit(requested)
        if parsed.scheme != 'https' or parsed.query or parsed.fragment:raise ValueError('请输入完整的 HTTPS 云端地址')
        requested = requested.rstrip('/')
        endpoint('wss'+requested[5:]+'/device')
        requested_ws = CloudManager.canonical_url('wss'+requested[5:]+'/device')
        if target is not None and CloudManager.canonical_url(active[target]['url']) != requested_ws:
            raise ValueError('重新绑定时不能更改云端地址')
        if target is None:
            target = next((key for key, config in active.items() if CloudManager.canonical_url(config['url']) == requested_ws), None)
            if target is None:
                # An explicitly selected new cloud starts its own binding, leaving existing bindings intact.
                clean = {k:v for k,v in state.items() if k not in ('deviceId','account','replacement','requestId','error')}
                return {**clean, 'state':'configured', 'url':requested}, None
    if not active:
        clean = {k:v for k,v in state.items() if k not in ('deviceId','account','replacement')}
        if state['state'] == 'bound': clean['state'] = 'configured'
        return clean, None
    if data.get('verify', True) is False and data.get('action', 'status') == 'status':
        return state, None
    if target is None:
        requested_url = 'wss'+state.get('url', '')[5:]+'/device'
        target = next((key for key,config in active.items() if CloudManager.canonical_url(config['url']) == CloudManager.canonical_url(requested_url)), None)
        if target is None:
            if len(active) != 1: return state, '请选择需要检查的云端绑定'
            target = next(iter(active))
    config = active[target]
    if not config['url'].startswith('wss://') or not config['url'].endswith('/device'):
        return state, '此云端不支持扫码绑定，请检查云端地址'
    url = 'https'+config['url'][3:-7]
    try:
        result = request(url, 'manage', {'action':'list','deviceId':config['deviceId'],'token':config['token']})
        if not isinstance(result.get('members'), list): raise ValueError('绑定验证响应无效')
    except InvalidDeviceCredentials:
        if target == 'legacy':
            # Migrate through the existing manager so recovery keeps the same identity.
            manager = CloudManager(None, directory)
            target = next(iter(manager.connections))
        replacement = {'id':target,'fingerprint':CloudManager.fingerprint(config)}
        recovered = {k:v for k,v in state.items() if k not in ('deviceId','account')}
        if state.get('replacement') != replacement: recovered.pop('requestId', None)
        return {**recovered, 'state':'configured', 'url':url, 'replacement':replacement}, None
    except (OSError, ValueError) as error:
        return state, '暂时无法验证云端绑定：'+str(error)
    return {**{k:v for k,v in state.items() if k != 'replacement'}, 'state':'bound', 'url':url, 'deviceId':config['deviceId']}, None
