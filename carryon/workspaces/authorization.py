"""One membership authority per explicitly joined workspace, independent transports."""
import hashlib
import json
import secrets


def authority(records, device):
    record = records.get(device)
    if record is None:
        raise PermissionError('工作区连接已撤销')
    identity = record.get('workspaceAuthority', device)
    root = records.get(identity)
    if root is None or root.get('workspaceAuthority', identity) != identity:
        raise PermissionError('工作区授权记录无效')
    return identity, root


def connections(records, device):
    identity, _ = authority(records, device)
    return [key for key, row in records.items() if row.get('workspaceAuthority', key) == identity]


def preview(server, device):
    identity, root = authority(server.config['devices'], device)
    members = root.get('members', {})
    payload = {'authority': identity, 'members': members, 'owner': root.get('ownerUserId')}
    revision = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'revision': revision, 'members': [{'account': server.auth.profile(key), 'permissions': value} for key, value in members.items()]}


def attach(server, device, data):
    """Called only by native management with verified source-device credentials."""
    from carryon.workspaces.connections import validate
    records = server.config['devices']
    identity, root = authority(records, device)
    workspace = validate(data.get('workspace'))
    source = records[device].get('workspace')
    if source and source['id'] != workspace['id']:
        raise PermissionError('连接不属于此工作区')
    request = data.get('requestId')
    if not isinstance(request, str) or len(request) != 32 or any(c not in '0123456789abcdef' for c in request):
        raise ValueError('连接申请编号无效')
    previous = root.get('connectionRequests', {}).get(request)
    if previous:
        saved = records.get(previous)
        if saved is None: raise PermissionError('此连接已撤销，不能重放加入请求')
        if saved.get('workspace') != workspace: raise ValueError('连接申请参数已改变')
        return {'deviceId': previous, 'token': saved['deviceToken'], 'state': 'bound'}
    if data.get('confirmed') is not True or data.get('revision') != preview(server, device)['revision']:
        raise PermissionError('请在电脑端重新核对工作区账号和权限并确认')
    if not root.get('ownerUserId') or not root.get('members'):
        raise PermissionError('工作区没有有效的已绑定账号')
    if len(records) >= 256: raise ValueError('连接数量已达上限')
    new_id = secrets.token_hex(16)
    child = {'name': workspace['name'], 'deviceToken': secrets.token_urlsafe(32),
             'apiToken': secrets.token_urlsafe(32), 'ownerUserId': root['ownerUserId'],
             'workspaceAuthority': identity, 'workspace': workspace}
    # No copy of members into children: future grant/revoke has one authority.
    updated = {**records, identity: {**root, 'workspaceAuthority': identity,
               'connectionRequests': {**root.get('connectionRequests', {}), request: new_id}}, new_id: child}
    server.save_devices(updated)
    return {'deviceId': new_id, 'token': child['deviceToken'], 'state': 'bound'}


def removing(records, device):
    """Promote authority atomically when its transport is removed; keep other bindings."""
    identity, root = authority(records, device)
    remaining = {key: dict(row) for key, row in records.items() if key != device}
    if identity == device:
        peers = [key for key in connections(records, device) if key != device]
        if peers:
            successor = peers[0]
            for key in peers: remaining[key]['workspaceAuthority'] = successor
            remaining[successor]['members'] = root.get('members', {})
            remaining[successor]['connectionRequests'] = root.get('connectionRequests', {})
    return remaining
