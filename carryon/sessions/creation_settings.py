"""The optional model selection for the first turn of a new conversation."""
from carryon.contracts import settings


def validate(value):
    if value is None: return None
    if not isinstance(value, dict) or set(value) - {'model', 'effort'}:
        raise ValueError('新会话设置仅支持模型与思考强度')
    return settings(value, 'new')


def apply(runtime, tid, value, before_send):
    if value is not None:
        runtime.request('thread-follower-update-thread-settings',
                        {'conversationId': tid, 'threadSettings': value}, before_send=before_send)
