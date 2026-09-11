"""Installed assets are immutable; credentials and journals belong to the user."""
import json
import os
import sys
from pathlib import Path


def state_dir():
    override = os.environ.get('CONNECTNOW_HOME')
    return Path(override).expanduser().resolve() if override else Path.home() / 'Library/Application Support/ConnectNow'


def assets():
    packaged = Path(__file__).parent / 'web'
    return packaged if packaged.is_dir() else Path(__file__).resolve().parent.parent


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def save_json(path, data):
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def command():
    return [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'connectnow']
