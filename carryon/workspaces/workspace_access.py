"""Workspace member capabilities, enforced before every console transport."""
from urllib.parse import urlsplit

CAPABILITIES = ('view', 'create', 'send', 'stop', 'edit', 'files', 'approve', 'resetQuota')


def permissions(value):
    if not isinstance(value, list) or any(v not in CAPABILITIES for v in value):
        raise ValueError('工作区权限无效')
    result = sorted(set(value))
    if result and 'view' not in result:
        raise ValueError('操作工作区需要查看权限')
    return result


def required_capabilities(method, target, body=None):
    path = urlsplit(target).path
    if path.endswith('/voice') or path.endswith('/voice/audio'): return ('send',)
    if method == 'GET':
        return ('files',) if '/images/' in path or '/artifacts/' in path or path.endswith('/files/search') else ('view',)
    if path.endswith('/streams') or '/streams/' in path or '/notifications/' in path:
        return ('view',)
    if path == '/api/usage/reset': return ('resetQuota',)
    if path.endswith('/plugins'): return ('edit',)
    if path.endswith('/skills/config'): return ('edit',)
    if path.endswith('/terminals'): return ('stop',)
    if path == '/api/sections' or path.startswith('/api/sections/'): return ('edit',)
    if path.endswith('/threads'):
        settings = (body or {}).get('settings')
        return ('create', 'edit') if isinstance(settings, dict) and set(settings) - {'model', 'effort'} else ('create',)
    if path.endswith('/fork') or path.endswith('/side-chats'):
        return ('create',)
    if path.startswith('/api/side-chats/') and path.endswith('/close'): return ('stop',)
    if path.endswith(('/archive', '/unarchive', '/rename', '/section')): return ('edit',)
    if path.endswith('/session'): return ('send',)
    if path.endswith('/messages') or path.endswith('/compose'):
        return ('send', 'files') if (body or {}).get('files') else ('send',)
    if path.endswith('/operations'):
        action = (body or {}).get('action')
        if action in ('interrupt', 'goal-pause', 'goal-clear', 'voice-stop'): return ('stop',)
        if action in ('steer', 'resume', 'queue-add', 'queue-resume', 'review', 'goal-set', 'voice-start'): return ('send', 'files') if (body or {}).get('files') else ('send',)
        if action in ('edit', 'compact', 'settings', 'queue-edit', 'queue-delete', 'queue-reorder', 'clear-queue'): return ('edit',)
        if action in ('command-approval', 'file-approval', 'permissions-approval', 'user-input', 'mcp-response'): return ('approve',)
    if path.endswith('/acknowledge'): return ('send',)
    raise PermissionError('此操作未获授权')


def granted(server, key, device):
    identity = server.auth.identity(key)
    record = server.config['devices'].get(device)
    if record is None:
        return []
    from carryon.workspaces.authorization import authority
    try: _, record = authority(server.config['devices'], device)
    except PermissionError: return []
    members = record.get('members', {})
    return members.get(identity, [])


def require(server, key, device, needed=('view',)):
    import time
    if server.sessions.get(key, 0) <= time.monotonic():
        raise PermissionError('登录已过期')
    if not set(needed).issubset(granted(server, key, device)):
        raise PermissionError('工作区未授权')
