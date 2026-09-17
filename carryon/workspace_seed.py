"""One-time credential/model initialization; never import conversation history."""
import json
import math
import os
import stat
from pathlib import Path
import tempfile

from .paths import default_codex_home, private_dir, save_json

MODEL_KEYS = {'model', 'model_provider', 'model_reasoning_effort', 'model_reasoning_summary',
              'model_verbosity', 'model_context_window', 'model_auto_compact_token_limit', 'service_tier'}


def toml_value(value):
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False)
    if type(value) is bool: return 'true' if value else 'false'
    if type(value) in (int, float) and math.isfinite(value): return str(value)
    if isinstance(value, list): return '[' + ', '.join(toml_value(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(k) + ' = ' + toml_value(v) for k, v in value.items()) + '}'
    raise ValueError('模型配置含不支持的 TOML 值，未初始化工作区')


def seed(home, source=None):
    """Called with the workspace home lock held. Existing files always win."""
    home = private_dir(Path(home).resolve())
    source = Path(source or default_codex_home()).resolve()
    marker = home / '.carryon-initialized.json'
    for name in ('auth.json', 'config.toml', '.carryon-initialized.json'):
        path = home / name
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('独立工作区的 ' + name + ' 必须是独立的普通文件，不能使用链接')
    if marker.exists(): return
    if source == home: raise ValueError('独立工作区不能使用默认 Codex 目录')
    files = {}
    config = source / 'config.toml'
    if not (home / 'config.toml').exists() and config.exists():
        try:
            import tomllib
        except ImportError:
            raise ValueError('首次导入模型配置需要 Python 3.11 或更高版本') from None
        raw = tomllib.loads(config.read_text())
        profiles, active = raw.get('profiles', {}), raw.get('profile')
        providers = raw.get('model_providers', {})
        if (not isinstance(profiles, dict) or active is not None and not isinstance(active, str)
                or not isinstance(providers, dict) or any(not isinstance(v, dict) for v in providers.values())):
            raise ValueError('默认 Codex 的模型配置结构无效，未初始化工作区')
        profile = profiles.get(active, {})
        if not isinstance(profile, dict): raise ValueError('默认 Codex 的 profile 配置无效')
        selected = {k: v for k, v in {**raw, **profile}.items() if k in MODEL_KEYS}
        if providers: selected['model_providers'] = providers
        files['config.toml'] = ''.join(k + ' = ' + toml_value(v) + '\n' for k, v in selected.items()).encode()
    auth = source / 'auth.json'
    if not (home / 'auth.json').exists() and auth.exists():
        data = auth.read_bytes()
        if not isinstance(json.loads(data), dict): raise ValueError('默认 Codex 登录配置无效')
        files['auth.json'] = data
    # Publish complete private files without replacing files created concurrently.
    for name, data in files.items():
        fd, temporary = tempfile.mkstemp(prefix='.carryon-seed-', dir=home)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            try: os.link(temporary, home / name)
            except FileExistsError: pass
        finally: os.unlink(temporary)
    save_json(marker, {'version': 1})
