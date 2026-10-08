"""Native first-turn configuration without changing the destination or ownership."""
from carryon.contracts import SCHEMAS, settings


def supported():
    return sorted(set(SCHEMAS['settings']['properties']) - {'threadId', 'cwd', 'projectId', 'activePermissionProfile', 'multiAgentMode'})


def validate(value):
    if value is None: return None
    if not isinstance(value, dict) or set(value) - set(supported()):
        raise ValueError('新会话设置不能改变目标目录、归属或只读原生字段')
    return settings(value, 'new')


def apply(runtime, tid, value, before_send):
    if value is not None:
        runtime.request('thread-follower-update-thread-settings',
                        {'conversationId': tid, 'threadSettings': value}, before_send=before_send)
