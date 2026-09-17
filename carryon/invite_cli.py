"""Registration invitations issued with this computer's private authority."""
import fcntl
import hashlib
import json
import secrets
from pathlib import Path

from .account_client import request
from .paths import private_dir, save_json


def issuer_token():
    # Shared by this computer's CLI/desktop, never stored in workspace bindings.
    directory = private_dir(Path.home() / 'Library/Application Support/CarryOn/invite-issuer')
    with (directory / 'issuer.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / 'credential.json'
        if not path.exists():
            save_json(path, {'token': secrets.token_urlsafe(32)})
        path.chmod(0o600)
        token = json.loads(path.read_text()).get('token')
        if not isinstance(token, str) or len(token) != 43:
            raise ValueError('本机邀请码凭证无效，请恢复原凭证')
        return token


def command(args):
    token = issuer_token()
    if args.setup:
        print(json.dumps({'issuerHash': hashlib.sha256(token.encode()).hexdigest()}))
        return 0
    url = args.url
    if not url:
        from .members_cli import binding
        url, _ = binding(args.state_dir, args.binding_id)
    result = request(url, 'invite', {'issuerToken': token})
    print(json.dumps(result, ensure_ascii=False))
    return 0
