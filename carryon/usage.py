"""Read account quota through the installed Codex app-server, never through a task."""
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import time
import threading
from contextlib import suppress

from .errors import BridgeError


def executable():
    bundled = Path('/Applications/ChatGPT.app/Contents/Resources/codex')
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    found = shutil.which('codex')
    if found:
        return found
    raise BridgeError('未找到本机 Codex 程序，无法读取额度', 503)


_slots = threading.BoundedSemaphore(2)


def native_read(home):
    if not _slots.acquire(blocking=False):
        raise BridgeError('额度查询正在处理，请稍后重试', 503)
    try:
        return _native_read(home)
    finally:
        _slots.release()


def _native_read(home):
    env = dict(os.environ, CODEX_HOME=str(Path(home).resolve()))
    process = subprocess.Popen([executable(), 'app-server'], cwd=str(home), env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    selector = None
    buffered = b''
    def send(value):
        process.stdin.write(json.dumps(value).encode() + b'\n')
        process.stdin.flush()
    def request(identifier, method, params):
        nonlocal buffered
        send({'id': identifier, 'method': method, 'params': params})
        while True:
            while b'\n' in buffered:
                line, buffered = buffered.split(b'\n', 1)
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise BridgeError("Codex 额度响应格式不正确", 502)
                if value.get('id') != identifier:
                    continue
                if 'error' in value:
                    raise BridgeError('Codex 暂时无法提供额度，请检查本机登录状态后重试', 503)
                return value.get('result')
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise BridgeError('读取 Codex 额度超时，请稍后重试', 504)
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise BridgeError('Codex 额度读取连接已关闭', 503)
            buffered += chunk
            if len(buffered) > 1024 * 1024:
                raise BridgeError('Codex 额度响应过大', 502)
    try:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        request(1, 'initialize', {'clientInfo': {'name': 'carryon_usage', 'version': '1.0'}})
        send({'method': 'initialized', 'params': {}})
        account = request(2, 'account/read', {'refreshToken': False})
        if not isinstance(account, dict) or not isinstance(account.get('account'), dict) or account['account'].get('type') != 'chatgpt':
            raise BridgeError('本机 Codex 未登录 ChatGPT 账号，暂无订阅额度数据', 503)
        return request(3, 'account/rateLimits/read', {})
    finally:
        if selector is not None:
            with suppress(OSError): selector.close()
        try:
            with suppress(OSError): process.stdin.close()
        finally:
            try:
                if process.poll() is None:
                    with suppress(OSError): process.terminate()
                try:
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    with suppress(OSError): process.kill()
                    with suppress(OSError, subprocess.TimeoutExpired): process.wait(timeout=2)
            finally:
                with suppress(OSError): process.stdout.close()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def project(raw):
    if not isinstance(raw, dict):
        raise BridgeError('Codex 额度数据格式不正确', 502)
    mapped = raw.get('rateLimitsByLimitId')
    entries = list(mapped.items()) if isinstance(mapped, dict) and mapped else [('codex', raw.get('rateLimits'))]
    limits = []
    for key, value in entries:
        if not isinstance(value, dict):
            continue
        windows = []
        for name in ('primary', 'secondary'):
            window = value.get(name)
            if not isinstance(window, dict):
                continue
            used, duration, reset = (window.get(k) for k in ('usedPercent', 'windowDurationMins', 'resetsAt'))
            windows.append({'id': name, 'usedPercent': max(0, min(100, used)) if number(used) else None,
                            'windowDurationMins': duration if number(duration) and duration > 0 else None,
                            'resetsAt': reset if number(reset) and reset > 0 else None})
        if windows:
            limits.append({'id': str(key), 'name': value.get('limitName') if isinstance(value.get('limitName'), str) else str(key),
                           'planType': value.get('planType') if isinstance(value.get('planType'), str) else None,
                           'windows': windows})
    return {'limits': limits, 'fetchedAt': time.time(), 'source': 'codex-account', 'scope': 'account'}


def read(home):
    try:
        return project(native_read(home))
    except BridgeError:
        raise
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        raise BridgeError('无法读取本机 Codex 额度，请检查 Codex 后重试', 503) from None
