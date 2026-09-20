"""Creation and backend identity for local workspaces."""
import fcntl
import secrets
from pathlib import Path
from .paths import default_codex_home, private_dir, save_json
from .services import catalog_directory, records, register


def backend(directory):
    value = records().get(str(Path(directory).resolve()), {}).get('backend', 'ipc')
    return 'ipc' if value == 'desktop-ipc' else value


def initialize(directory):
    directory = Path(directory).resolve()
    root = private_dir(catalog_directory())
    with (root/'workspace-creation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = records()
        if str(directory) in existing:
            if existing[str(directory)].get('removed'):
                raise ValueError('工作区已删除，请显式重新注册后再启动')
            return existing[str(directory)]
        ipc = next((row for row in existing.values() if not row.get('removed') and row.get('backend','ipc') in ('ipc','desktop-ipc')), None)
        if ipc:
            raise ValueError('本机已有 Codex App 工作区：'+ipc['directory']+'；请使用新建工作区创建独立环境')
        private_dir(directory)
        return register(directory, name='本机 Codex', port=0, codex_home=default_codex_home(), backend='ipc')


def create(name='新工作区'):
    from .usage import executable
    executable()  # Refuse a configuration that cannot start Codex.
    if not isinstance(name, str) or not name.strip() or len(name) > 100: raise ValueError('工作区名称应为 1–100 个字符')
    root = private_dir(catalog_directory())
    with (root/'workspace-creation.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        directory = private_dir(root/'Workspaces'/secrets.token_hex(16))
        home = private_dir(directory/'codex')
        private_dir(directory/'projects')
        # No credential or session copy. Account login belongs to this CODEX_HOME.
        (home/'config.toml').write_text('approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n')
        return register(directory, name=name, port=0, codex_home=home, backend='app-server')
