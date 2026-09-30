"""Explicit, account-bound redemption using the native idempotency contract."""
import re
import time
from carryon.contracts import digest, validate_request_id
from carryon.errors import BridgeError
from carryon.usage import native_consume

OUTCOMES = {'reset', 'nothingToReset', 'noCredit', 'alreadyRedeemed'}


def submit(bridge, data, source=None, authorize=None):
    request_id = data.get('requestId')
    validate_request_id(request_id)
    account = data.get('accountKey')
    if data.get('confirmed') is not True: raise ValueError('使用重置卡前需要确认')
    if not isinstance(account, str) or not re.fullmatch(r'[0-9a-f]{64}', account):
        raise ValueError('请刷新额度以核对 Codex 账号')
    credit = data.get('creditId')
    if credit is not None and (not isinstance(credit, str) or not 1 <= len(credit) <= 512):
        raise ValueError('重置卡标识无效')
    if set(data) - {'requestId', 'accountKey', 'confirmed', 'creditId'}: raise ValueError('未知重置参数')
    ipc, generation = bridge.require()
    target = 'quota:' + account
    fingerprint = digest([target, credit])
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        previous = bridge.journal.get(request_id)
        retrying = bool(previous and previous['state'] == 'uncertain')
        if previous:
            if previous['kind'] != 'quota-reset' or previous['fingerprint'] != fingerprint:
                raise BridgeError('requestId 已用于不同内容', 409)
            if previous['state'] != 'uncertain': return previous
        else:
            for job in bridge.journal.list():
                if job['kind'] == 'quota-reset' and job['threadId'] == target and job['state'] in ('preparing', 'dispatching', 'uncertain'):
                    raise BridgeError('已有重置结果待确认，请使用原请求重试', 409)
            previous = {'id': request_id, 'fingerprint': fingerprint, 'kind': 'quota-reset',
                        'threadId': target, 'created': time.time(), 'state': 'preparing'}
            if source: previous.update(source)
            bridge.journal.insert(previous)
        # Reserve explicit retry before releasing the lock. Never replay in a background refresh.
        bridge.journal.update(request_id, state='dispatching' if retrying else 'preparing', error=None)
    sent = False
    try:
        def guarded(write):
            nonlocal sent
            with bridge.lock:
                bridge.check_generation(ipc, generation)
                if authorize: authorize()
                bridge.journal.update(request_id, state='dispatching')
                sent = True
                write()
        params = {'idempotencyKey': request_id}
        if credit is not None: params['creditId'] = credit
        result = native_consume(bridge.catalog.home, account, params, guarded)
        if not isinstance(result, dict) or result.get('outcome') not in OUTCOMES:
            raise ValueError('原生重置回执无效')
        bridge.journal.update(request_id, state='completed', result={'outcome': result['outcome']},
                              evidence='native-reset-credit-response', error=None)
    except Exception:
        uncertain = sent or retrying
        bridge.journal.update(request_id, state='uncertain' if uncertain else 'failed',
                              error='重置结果尚未确认，请沿用原请求重试' if uncertain else '重置未发送，请检查账号、连接与授权后重试')
    return bridge.journal.get(request_id)
