"""Installed assets are immutable; credentials and journals belong to the user."""
import json
import os
import sys
from pathlib import Path


def state_dir():
    override = os.environ.get('CARRYON_HOME')
    return Path(override).expanduser().resolve() if override else Path.home() / 'Library/Application Support/CarryOn'


def default_codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home()/".codex").expanduser().resolve()


def workspace_backend(directory):
    from .services import records
    directory = Path(directory).expanduser().resolve()
    saved = records().get(str(directory), {}).get('backend')
    if saved in ('ipc', 'desktop-ipc'): return 'desktop-ipc'
    if saved == 'app-server': return saved
    return 'desktop-ipc' if directory == state_dir().resolve() else 'app-server'


def workspace_codex_home(directory, configured=None):
    """Old shared-home registrations become isolated on the next service start.

    No history or credentials are copied, moved, or deleted.
    """
    directory = Path(directory).expanduser().resolve()
    home = Path(configured).expanduser().resolve() if configured else None
    if workspace_backend(directory) == 'desktop-ipc':
        return home or default_codex_home()
    shared = {default_codex_home(), (Path.home() / '.codex').resolve()}
    result = (directory / 'codex-home').resolve() if home is None or home in shared else home
    if result in shared: raise ValueError('独立工作区目录不能链接到默认 Codex 目录')
    return result


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
    return [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'carryon']
