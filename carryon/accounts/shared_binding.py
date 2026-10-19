"""Explicit native confirmation for adding an unbound connection to a bound workspace."""
import json
import secrets
from pathlib import Path

from carryon.cloud.cloud_manager import CloudManager
from carryon.paths import save_json
from carryon.services import records
from carryon.workspaces.connections import descriptor


def candidates(directory):
    directory = str(Path(directory).resolve())
    rows = records(); target = rows.get(directory, {})
    if not target.get('workspaceId'): return []
    existing = {CloudManager.canonical_url(c['url']) for c in CloudManager.saved_bindings(directory).values()}
    result = []
    for path, row in rows.items():
        if path == directory or row.get('removed') or row.get('workspaceId') != target['workspaceId']: continue
        for binding, config in CloudManager.saved_bindings(path).items():
            if not config.get('enabled') or CloudManager.canonical_url(config['url']) in existing: continue
            if not config['url'].startswith('wss://') or not config['url'].endswith('/device'): continue
            result.append({'directory': path, 'bindingId': binding, 'name': row.get('workspaceName', row.get('name', '工作区')),
                           'url': 'https' + config['url'][3:-7]})
    return result


def source(directory, path, binding_id):
    rows = records(); target = rows[str(Path(directory).resolve())]
    if not isinstance(path, str) or not path: raise ValueError('请选择已绑定连接')
    path = str(Path(path).expanduser().resolve()); row = rows.get(path)
    if not target.get('workspaceId') or not row or row.get('removed') or path == str(Path(directory).resolve()) or row.get('workspaceId') != target.get('workspaceId'):
        raise ValueError('请选择同一工作区的已绑定连接')
    config = CloudManager.saved_bindings(path).get(binding_id)
    if not config or not config.get('enabled'): raise ValueError('原连接绑定已改变，请重新选择')
    url = config['url']
    if not url.startswith('wss://') or not url.endswith('/device'): raise ValueError('此云端不支持共享工作区绑定')
    return target, config, 'https'+url[3:-7]


def pending_preview(directory):
    path = Path(directory)/'shared-connection.json'
    if not path.exists(): return None
    pending = json.loads(path.read_text())
    if pending.get('completed') or pending.get('cancelled'): return None
    return {'shareConfirmation': pending['confirmation'], 'members': pending['members'],
            'url': pending['url'], 'control': pending['control'], 'submitted': pending.get('submitted', False)}


def exchange(directory, data):
    from carryon.accounts.onboarding import request, install_binding
    path = directory/'shared-connection.json'
    action = data['action']
    if type(data.get('autoStart', True)) is not bool: raise ValueError('autoStart 必须为布尔值')
    if action == 'share-cancel':
        if path.exists():
            pending = json.loads(path.read_text())
            if pending.get('submitted') and not pending.get('completed'):
                raise ValueError('加入请求结果尚未确认，请保留原请求并重试')
            pending['cancelled'] = True; save_json(path, pending)
        return {'state': 'cancelled'}
    if action == 'share-preview':
        target, config, url = source(directory, data.get('sourceDirectory', ''), data.get('sourceBindingId'))
        CloudManager(None, directory).check_available(config['url'])
        view = request(url, 'manage', {'action': 'connection-preview', 'deviceId': config['deviceId'], 'token': config['token']})
        if not isinstance(view.get('members'), list) or not isinstance(view.get('revision'), str):
            raise ValueError('工作区授权预览无效，请更新云端')
        pending = {'confirmation': secrets.token_hex(16), 'requestId': secrets.token_hex(16),
                   'sourceDirectory': data['sourceDirectory'], 'sourceBindingId': data['sourceBindingId'],
                   'sourceFingerprint': CloudManager.fingerprint(config), 'workspace': descriptor(target),
                   'revision': view['revision'], 'members': view['members'], 'url': url,
                   'control': config.get('control', False)}
        # Never overwrite an uncertain remote attach with a fresh request ID.
        if path.exists():
            previous = json.loads(path.read_text())
            if previous.get('submitted') and not previous.get('completed'):
                raise ValueError('已有待恢复的加入请求，请重试原确认操作')
        save_json(path, pending)
        return {'state': 'share-preview', 'shareConfirmation': pending['confirmation'],
                'members': view['members'], 'url': url, 'control': pending['control'], 'submitted': False}
    if action != 'share-confirm' or data.get('confirmed') is not True:
        raise ValueError('请在电脑端确认开放此连接')
    if not path.exists(): raise ValueError('请先预览工作区账号和权限')
    pending = json.loads(path.read_text())
    if pending.get('cancelled') or data.get('shareConfirmation') != pending['confirmation']: raise ValueError('确认信息已失效，请重新预览')
    target, config, url = source(directory, pending['sourceDirectory'], pending['sourceBindingId'])
    if (CloudManager.fingerprint(config) != pending['sourceFingerprint'] or descriptor(target) != pending['workspace']
            or config.get('control', False) != pending['control']):
        raise ValueError('连接配置已改变，请重新核对')
    if 'result' not in pending:
        CloudManager(None, directory).check_available(config['url'])
    pending['submitted'] = True; save_json(path, pending)
    from carryon.accounts.onboarding import BindingRequestError
    try:
        result = request(url, 'manage', {'action': 'connection-attach', 'deviceId': config['deviceId'], 'token': config['token'],
            'confirmed': True, 'revision': pending['revision'], 'requestId': pending['requestId'], 'workspace': pending['workspace']})
    except BindingRequestError as error:
        if error.status in (400, 403):
            pending['submitted'] = False; save_json(path, pending)
        raise
    new_config = {'enabled': True, 'url': config['url'], 'deviceId': result.get('deviceId'),
                  'token': result.get('token'), 'control': pending['control']}
    from carryon.cloud.cloud import CloudConnector
    CloudConnector.validate(new_config)
    pending['result'] = result; save_json(path, pending)
    install_binding(directory, new_config)
    pending['completed'] = True; save_json(path, pending)
    # Keep request journal: retries cannot create or replay a second attachment.
    return {'state': 'bound', 'url': url, 'deviceId': result['deviceId'], 'autoStart': data.get('autoStart', True)}
