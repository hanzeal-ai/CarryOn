"""Workspace member capabilities, enforced before every console transport."""
from urllib.parse import urlsplit

CAPABILITIES = ('view', 'create', 'send', 'stop', 'edit', 'files', 'approve')


def permissions(value):
    if not isinstance(value, list) or any(v not in CAPABILITIES for v in value):
        raise ValueError('工作区权限无效')
    result = sorted(set(value))
    if result and 'view' not in result:
        raise ValueError('操作工作区需要查看权限')
    return result


def capability(method, target, body=None):
    path = urlsplit(target).path
    if method == 'GET':
        return 'files' if '/images/' in path or '/artifacts/' in path else 'view'
    if path.endswith('/streams') or '/streams/' in path or '/notifications/' in path:
        return 'view'
    if path.endswith('/threads'):
        return 'create'
    if path.endswith('/messages') or path.endswith('/compose'):
        return 'send'
    if path.endswith('/operations'):
        action = (body or {}).get('action')
        if action == 'interrupt': return 'stop'
        if action in ('steer', 'resume', 'queue-add', 'queue-resume'): return 'send'
        if action in ('edit', 'compact', 'settings', 'queue-edit', 'queue-delete', 'queue-reorder', 'clear-queue'): return 'edit'
        if action in ('command-approval', 'file-approval', 'permissions-approval', 'user-input', 'mcp-response'): return 'approve'
    if path.endswith('/acknowledge'): return 'send'
    raise PermissionError('此操作未获授权')


def granted(server, key, device):
    identity = server.auth.identity(key)
    record = server.config['devices'].get(device)
    if record is None:
        return []
    members = record.get('members', {})
    return members.get(identity, [])


def require(server, key, device, needed='view'):
    import time
    if server.sessions.get(key, 0) <= time.monotonic():
        raise PermissionError('登录已过期')
    if needed not in granted(server, key, device):
        raise PermissionError('工作区未授权')
