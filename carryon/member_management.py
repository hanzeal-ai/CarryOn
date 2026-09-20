"""Native workstation authority manages only its own workspace memberships."""
import secrets

from .workspace_access import CAPABILITIES, permissions


def device_record(server, data):
    if not isinstance(data, dict): raise ValueError('设备凭证格式无效')
    device, token = data.get('deviceId'), data.get('token')
    if not isinstance(device, str) or not isinstance(token, str): raise PermissionError('设备凭证无效')
    record = server.config['devices'].get(device)
    if record is None or not secrets.compare_digest(token, record['deviceToken']): raise PermissionError('设备凭证无效')
    return device, record


def manage(server, data):
    with server.auth_lock, server.binding_invites.lock, server.lock:
        device, record = device_record(server, data)
        action = data.get('action')
        members = record.get('members', {'owner':list(CAPABILITIES)})
        if action == 'list':
            return {'members':[{'account':server.auth.profile(identity), 'permissions':value} for identity,value in members.items()]}
        if action == 'invite':
            result = server.binding_invites.start({'name':record.get('name',device), 'permissions':data.get('permissions')})
            entry = server.binding_invites.entries[result['id']]
            entry['workspaceId'] = device
            server.binding_invites.save()
            return result
        if action == 'poll':
            entry = server.binding_invites.entry({'id':data.get('id'),'secret':data.get('secret')}, 'poll')
            if entry.get('workspaceId') != device: raise PermissionError('邀请不属于此工作区')
            return server.binding_invites.poll(data)
        identity = data.get('accountId')
        server.auth.profile(identity)
        if action == 'confirm':
            entry = server.binding_invites.entry({'id':data.get('id'),'secret':data.get('secret')}, 'poll')
            if entry.get('workspaceId') != device or entry.get('account') != identity or entry['state'] not in ('accepted','bound'):
                raise PermissionError('请先由使用者扫码接受，再核对账号确认')
            if entry['state'] == 'bound':
                if identity not in members: raise PermissionError('授权已撤销，请重新生成邀请')
                return {'updated':True}
            allowed = entry['permissions']
        elif action == 'grant':
            allowed = permissions(data.get('permissions'))
            if identity not in members: raise PermissionError('请使用绑定申请，由手机确认新账号授权')
        elif action == 'revoke':
            if identity not in members: return {'removed':True}
            allowed = []
        else: raise ValueError('成员操作无效')
        updated = {**members}
        if allowed: updated[identity] = allowed
        else: updated.pop(identity, None)
        server.save_devices({**server.config['devices'],device:{**record,'members':updated}})
        if 'view' not in allowed:
            streams = [sid for sid, stream in server.console_streams.items()
                       if stream['device'] == device and server.auth.identity(stream['session']) == identity]
            for sid in streams:
                server.release_stream(sid)
        if action == 'confirm':
            entry['state'] = 'bound'
            server.binding_invites.save()
        return {'updated':True}
