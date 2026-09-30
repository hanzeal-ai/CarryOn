"""Read quota and explicitly redeem reset credits through the native app-server."""
import json
import hashlib
import math
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import time
import threading
from contextlib import suppress

from carryon.errors import BridgeError


def executable():
    current = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')
    if current.is_file() and os.access(current, os.X_OK):
        return str(current)
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


def native_consume(home, account_key, params, before_send):
    if not _slots.acquire(blocking=False):
        raise BridgeError('额度操作正在处理，请稍后重试', 503)
    try:
        return _native_read(home, (account_key, params), before_send)
    finally:
        _slots.release()


def account_key(raw):
    value = raw.get('accountId')
    return hashlib.sha256(value.encode()).hexdigest() if isinstance(value, str) and value else None


def _native_read(home, consume=None, before_send=None):
    env = dict(os.environ, CODEX_HOME=str(Path(home).resolve()))
    process = subprocess.Popen([executable(), 'app-server'], cwd=str(home), env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    selector = None
    buffered = b''
    def send(value):
        process.stdin.write(json.dumps(value).encode() + b'\n')
        process.stdin.flush()
    def request(identifier, method, params, guard=None):
        nonlocal buffered
        payload = {'id': identifier, 'method': method, 'params': params}
        if guard: guard(lambda: send(payload))
        else: send(payload)
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
        request(1, 'initialize', {'clientInfo': {'name': 'carryon_usage', 'version': '1.0'},
                                  **({'capabilities': {'experimentalApi': True}} if consume is not None else {})})
        send({'method': 'initialized', 'params': {}})
        account = request(2, 'account/read', {'refreshToken': False})
        if not isinstance(account, dict) or not isinstance(account.get('account'), dict) or account['account'].get('type') != 'chatgpt':
            raise BridgeError('本机 Codex 未登录 ChatGPT 账号，暂无订阅额度数据', 503)
        usage = request(3, 'account/rateLimits/read', {})
        if consume is None: return usage
        expected, params = consume
        if not isinstance(usage, dict) or account_key(usage) != expected:
            raise BridgeError('Codex 账号已改变或无法核对，请刷新额度后再操作', 409)
        return request(4, 'account/rateLimitResetCredit/consume', params, guard=before_send)
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


def reset_credits(value):
    if not isinstance(value, dict): return None
    count = value.get('availableCount')
    count = count if type(count) is int and count >= 0 else None
    details = value.get('credits')
    credits = None
    if isinstance(details, list):
        credits = []
        for credit in details:
            if not isinstance(credit, dict) or not isinstance(credit.get('id'), str): continue
            row = {'id': credit['id'],
                   'title': credit.get('title') if isinstance(credit.get('title'), str) else None,
                   'status': credit.get('status') if credit.get('status') in ('available', 'redeeming', 'redeemed') else 'unknown'}
            for key in ('grantedAt', 'expiresAt'):
                timestamp = credit.get(key)
                row[key] = timestamp if type(timestamp) is int and timestamp >= 0 else None
            credits.append(row)
    # Native details may be capped; their length is never the available count.
    return {'availableCount': count, 'credits': credits}


def project(raw):
    if not isinstance(raw, dict):
        raise BridgeError('Codex 额度数据格式不正确', 502)
    mapped = raw.get('rateLimitsByLimitId')
    entries = mapped.items() if isinstance(mapped, dict) else []
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
    return {'limits': limits, 'accountKey': account_key(raw), 'rateLimitResetCredits': reset_credits(raw.get('rateLimitResetCredits')),
            'fetchedAt': time.time(), 'source': 'codex-account', 'scope': 'account'}


def read(home):
    try:
        return project(native_read(home))
    except BridgeError:
        raise
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        raise BridgeError('无法读取本机 Codex 额度，请检查 Codex 后重试', 503) from None
