"""Native persisted skill enablement, validated against its destination inventory."""
import threading
import time
from pathlib import Path
from carryon.codex_protocol.read_control import reader
from carryon.contracts import digest, validate_request_id
from carryon.errors import IPCError
from carryon.errors import BridgeError
from carryon.sessions.native_metadata import configuration_cwd, configuration_busy, supported
from carryon.sessions.skills import catalog


def selected(runtime, cwd, path):
    rows = catalog(runtime, cwd)['skills']
    matches = [row for row in rows if row.get('path') == path]
    if len(matches) != 1 or type(matches[0].get('enabled')) is not bool: raise IPCError('技能已不存在或配置身份无效，请刷新')
    return matches[0]


def submit(bridge, tid, data, source=None, authorize=None):
    if not isinstance(data, dict) or set(data) != {'requestId', 'path', 'enabled'}: raise ValueError('技能配置字段无效')
    if not isinstance(data['path'], str) or not 0 < len(data['path']) <= 4096 or '\x00' in data['path'] or not Path(data['path']).is_absolute() or type(data['enabled']) is not bool: raise ValueError('技能配置身份或状态无效')
    key = data['requestId']; validate_request_id(key)
    body = {'path': data['path'], 'enabled': data['enabled']}
    ipc, generation = bridge.require()
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        if not supported(bridge): raise IPCError('当前连接不支持原生技能配置')
        fingerprint = digest(['skill-config', tid, body]); prior = bridge.journal.get(key)
        if prior:
            if prior['fingerprint'] != fingerprint: raise BridgeError('requestId已用于不同内容')
            return prior
        bridge.assert_target(tid); cwd = configuration_cwd(bridge, tid)
        if configuration_busy(bridge): raise IPCError('技能配置待核对，请先核对原请求')
        if any(job['threadId'] == tid and job['kind'] in ('archive', 'unarchive') and job['state'] in ('preparing', 'dispatching', 'uncertain') for job in bridge.journal.list()): raise IPCError('归档操作待核对，请先核对原请求')
        job = {'id': key, 'kind': 'skill-config', 'threadId': tid, 'body': body, 'cwd': cwd, 'fingerprint': fingerprint, 'state': 'preparing', 'created': time.time(), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=run, args=(bridge, ipc, generation, job, authorize), daemon=True, name='native-skill-config').start()
    return bridge.journal.get(key)


def confirmed(runtime, verify, job):
    row = selected(runtime, job['cwd'], job['body']['path']); verify()
    if row['enabled'] != job['body']['enabled']: raise IPCError('原生技能配置尚未确认', uncertain=True)
    return {'threadId': job['threadId'], 'path': job['body']['path'], 'enabled': row['enabled']}


def run(bridge, ipc, generation, job, authorize):
    sent = replied = False
    try:
        with reader(bridge) as (runtime, verify):
            selected(runtime, job['cwd'], job['body']['path']); verify()
            def guarded(write):
                nonlocal sent
                with bridge.lock:
                    verify(); bridge.check_generation(ipc, generation)
                    if authorize: authorize()
                    bridge.assert_target(job['threadId'])
                    if configuration_cwd(bridge, job['threadId']) != job['cwd']: raise IPCError('技能所属项目已改变')
                    bridge.journal.update(job['id'], state='dispatching'); sent = True; write()
            reply = runtime.rpc('skills/config/write', job['body'], guarded); replied = True
            if not isinstance(reply, dict) or reply.get('effectiveEnabled') is not job['body']['enabled']: raise IPCError('技能配置原生回执不匹配', uncertain=True)
            result = confirmed(runtime, verify, job)
            with bridge.lock:
                verify(); bridge.check_generation(ipc, generation)
                if authorize: authorize()
                if configuration_cwd(bridge, job['threadId']) != job['cwd']: raise IPCError('技能所属项目已改变')
                bridge.journal.update(job['id'], state='completed', result=result, error=None, evidence='native-skill-config')
    except Exception as error:
        uncertain = sent and (replied or not isinstance(error, IPCError) or error.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(error))
    finally: bridge.notify()


def recover(bridge, job):
    if configuration_cwd(bridge, job['threadId']) != job['cwd']: return job
    with reader(bridge) as (runtime, verify):
        try: result = confirmed(runtime, verify, job)
        except IPCError: return job
        with bridge.lock:
            verify()
            if configuration_cwd(bridge, job['threadId']) != job['cwd']: return job
            return bridge.journal.update(job['id'], expected=job, state='completed', result=result, error=None, evidence='native-skill-config-confirmed')
