"""Read the desktop's identity-scoped persisted read state without modifying it."""
import base64
import hashlib
import json
import os
import math
from carryon.sessions.catalog import ID
from pathlib import Path


def _hash(values):
    return hashlib.sha256(json.dumps(values, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def event_time(turn):
    if turn.get('status') not in ('completed', 'failed', 'interrupted'):
        return None
    start, duration = turn.get('turnStartedAtMs'), turn.get('durationMs')
    if all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in (start, duration)):
        return (start + duration) / 1000
    return None


class DesktopReadState:
    def __init__(self, home):
        self.home = Path(home)

    def identity(self):
        try:
            auth = json.loads((self.home / 'auth.json').read_text())
            if auth.get('auth_mode') not in ('chatgpt', 'chatgptAuthTokens'):
                raise ValueError('unsupported identity')
            token = auth['tokens']['access_token'].split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)))['https://api.openai.com/auth']
            account = claims.get('chatgpt_account_id') or claims.get('account_id')
            user = claims.get('user_id') or claims.get('chatgpt_user_id')
            if not all(isinstance(value, str) and value for value in (account, user)):
                raise ValueError('missing principal')
            return _hash(['chatgpt', account, user])
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise ValueError('无法确认 Codex 桌面端账号，已读状态未同步') from None

    def capture(self):
        identity = self.identity()
        try:
            path = self.home / '.codex-global-state.json'
            with path.open() as stream:
                modified = os.fstat(stream.fileno()).st_mtime
                state = json.load(stream)['electron-thread-read-state-v1']
            if type(state['version']) is not int or state['version'] != 1:
                raise ValueError('unsupported version')
            # The local desktop IPC workspace uses the native local process,
            # never a remote/websocket execution host with the same display name.
            host = 'local:' + _hash(['local', 'local', None])
            unread = state['unreadByIdentity'][identity][host]
            if not isinstance(unread, list) or not all(isinstance(tid, str) and ID.fullmatch(tid) for tid in unread):
                raise ValueError('invalid unread list')
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError('无法读取当前账号及主机的桌面已读状态') from None
        if self.identity() != identity:
            raise ValueError('Codex 桌面端账号已切换，请重新刷新')
        return identity, set(unread), modified
