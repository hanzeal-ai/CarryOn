"""Native marketplace inventory and persisted plugin installation receipts."""
import threading
import time
from pathlib import Path
from carryon.codex_protocol.read_control import reader
from carryon.contracts import digest, validate_request_id
from carryon.errors import IPCError
from carryon.errors import BridgeError
from carryon.sessions.native_metadata import configuration_cwd, configuration_busy, supported


def inventory(runtime, cwd, verify):
    result = runtime.rpc('plugin/list', {'cwds': [cwd], 'forceRefetch': True}); verify()
    if not isinstance(result, dict) or not isinstance(result.get('marketplaces'), list): raise IPCError('原生插件目录无效')
    rows, identities = [], set()
    for marketplace in result['marketplaces']:
        if not isinstance(marketplace, dict) or not isinstance(marketplace.get('name'), str) or not isinstance(marketplace.get('plugins'), list): raise IPCError('原生插件市场格式无效')
        path = marketplace.get('path')
        if path is not None and (not isinstance(path, str) or not Path(path).is_absolute()): raise IPCError('原生插件市场路径无效')
        for plugin in marketplace['plugins']:
            if not isinstance(plugin, dict) or not isinstance(plugin.get('id'), str) or not plugin['id'] or not isinstance(plugin.get('name'), str) or not plugin['name'] or type(plugin.get('installed')) is not bool or type(plugin.get('enabled')) is not bool: raise IPCError('原生插件身份无效')
            if plugin['id'] in identities: raise IPCError('原生插件身份重复，无法确定安装来源')
            identities.add(plugin['id']); rows.append({**plugin, 'marketplaceName': marketplace['name'], 'marketplacePath': path})
    errors = result.get('marketplaceLoadErrors', [])
    if not isinstance(errors, list): raise IPCError('插件市场错误格式无效')
    return {'plugins': rows, 'errors': errors}



def discovery_context(value):
    if not isinstance(value, dict) or set(value) != {'searchTerm', 'scope', 'cursor'}: raise ValueError('插件搜索身份无效')
    term, scope, cursor = value['searchTerm'], value['scope'], value['cursor']
    if not isinstance(term, str) or not 0 < len(term.strip()) <= 200 or term != term.strip() or '\x00' in term or scope not in ('global', 'workspace', 'personal'): raise ValueError('插件搜索范围无效')
    if cursor is not None and (not isinstance(cursor, str) or not 0 < len(cursor) <= 4096 or '\x00' in cursor): raise ValueError('插件搜索游标无效')
    return dict(value)


def search_inventory(runtime, cwd, context, verify):
    context = discovery_context(context)
    params = {'cwds': [cwd], 'limit': 30, 'searchTerm': context['searchTerm'], 'scope': context['scope']}
    if context['cursor'] is not None: params['cursor'] = context['cursor']
    result = runtime.rpc('plugin/search', params); verify()
    if not isinstance(result, dict) or not isinstance(result.get('data'), list): raise IPCError('原生插件搜索回执无效')
    cursor = result.get('nextCursor')
    if cursor is not None and (not isinstance(cursor, str) or not 0 < len(cursor) <= 4096 or '\x00' in cursor or cursor == context['cursor']): raise IPCError('原生插件搜索游标无效')
    rows, identities = [], set()
    for hit in result['data']:
        if not isinstance(hit, dict) or not isinstance(hit.get('marketplaceName'), str) or not hit['marketplaceName']: raise IPCError('原生插件市场身份无效')
        path, plugin = hit.get('marketplacePath'), hit.get('plugin')
        if path is not None and (not isinstance(path, str) or not Path(path).is_absolute()): raise IPCError('原生插件市场路径无效')
        if not isinstance(plugin, dict) or not isinstance(plugin.get('id'), str) or not plugin['id'] or not isinstance(plugin.get('name'), str) or not plugin['name'] or type(plugin.get('installed')) is not bool or type(plugin.get('enabled')) is not bool: raise IPCError('原生插件搜索身份无效')
        if plugin['id'] in identities: raise IPCError('插件搜索身份重复，无法确定来源')
        identities.add(plugin['id'])
        rows.append({**plugin, 'marketplaceName': hit['marketplaceName'], 'marketplacePath': path, 'discovery': context})
    return {'plugins': rows, 'nextCursor': cursor, 'errors': []}


def detail_for(runtime, plugin, verify):
    response = runtime.rpc('plugin/read', selector(plugin)); verify()
    detail = response.get('plugin') if isinstance(response, dict) else None
    if (not isinstance(detail, dict) or not isinstance(detail.get('summary'), dict)
            or detail['summary'].get('id') != plugin['id'] or detail['summary'].get('name') != plugin['name']
            or detail.get('marketplaceName') != plugin['marketplaceName'] or detail.get('marketplacePath') != plugin['marketplacePath']
            or detail['summary'].get('source') != plugin.get('source')): raise IPCError('插件详情身份不匹配')
    summary = detail['summary']
    if type(summary.get('installed')) is not bool or type(summary.get('enabled')) is not bool: raise IPCError('插件详情状态无效')
    return detail


def selector(plugin):
    return {'pluginName': plugin['name'], **({'marketplacePath': plugin['marketplacePath']} if plugin['marketplacePath'] is not None else {'remoteMarketplaceName': plugin['marketplaceName']})}


def find(runtime, cwd, pid, verify, discovery=None):
    page = search_inventory(runtime, cwd, discovery, verify) if discovery is not None else inventory(runtime, cwd, verify)
    matches = [p for p in page['plugins'] if p['id'] == pid]
    if len(matches) != 1: raise IPCError('插件不属于当前项目目录，请刷新')
    if discovery is not None:
        detail = detail_for(runtime, matches[0], verify)
        return {**matches[0], **detail['summary']}
    return matches[0]


def read(bridge, tid, plugin_id=None, authorize=None, discovery=None):
    if discovery is not None: discovery = discovery_context(discovery)
    if plugin_id is not None and (not isinstance(plugin_id, str) or not 0 < len(plugin_id) <= 4096): raise ValueError('插件身份无效')
    ipc, generation = bridge.require(); bridge.assert_target(tid); cwd = configuration_cwd(bridge, tid)
    def check():
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if authorize: authorize()
            if configuration_cwd(bridge, tid) != cwd: raise IPCError('插件所属项目已改变')
    with reader(bridge) as (runtime, verify):
        check(); result = search_inventory(runtime, cwd, discovery, verify) if discovery is not None else inventory(runtime, cwd, verify)
        if plugin_id is not None:
            selected = [row for row in result['plugins'] if row['id'] == plugin_id]
            if len(selected) != 1: raise IPCError('插件不属于当前项目目录')
            detail = detail_for(runtime, selected[0], verify)
            result = {'plugin': {**detail, **({'discovery': discovery} if discovery is not None else {})}}
        check(); return {'threadId': tid, **result}


def submit(bridge, tid, data, source=None, authorize=None):
    if not isinstance(data, dict) or set(data) not in ({'requestId', 'action', 'pluginId'}, {'requestId', 'action', 'pluginId', 'discovery'}) or data['action'] not in ('install', 'uninstall') or not isinstance(data['pluginId'], str) or not 0 < len(data['pluginId']) <= 4096: raise ValueError('插件管理字段无效')
    key = data['requestId']; validate_request_id(key); body = {k: v for k, v in data.items() if k != 'requestId'}
    if 'discovery' in data: body['discovery'] = discovery_context(data['discovery'])
    ipc, generation = bridge.require()
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        if not supported(bridge): raise IPCError('当前连接不支持原生插件管理')
        fingerprint = digest(['plugin', tid, body]); prior = bridge.journal.get(key)
        if prior:
            if prior['fingerprint'] != fingerprint: raise BridgeError('requestId已用于不同内容')
            return prior
        bridge.assert_target(tid); cwd = configuration_cwd(bridge, tid)
        if configuration_busy(bridge): raise IPCError('工作区配置待核对，请先核对原请求')
        if any(j['threadId'] == tid and j['kind'] in ('archive', 'unarchive') and j['state'] in ('preparing', 'dispatching', 'uncertain') for j in bridge.journal.list()): raise IPCError('归档操作待核对，请先核对原请求')
        job = {'id': key, 'kind': 'plugin-' + body['action'], 'threadId': tid, 'body': body, 'cwd': cwd, 'fingerprint': fingerprint, 'state': 'preparing', 'created': time.time(), **(source or {})}; bridge.journal.insert(job)
    threading.Thread(target=run, args=(bridge, ipc, generation, job, authorize), daemon=True, name='native-plugin-' + body['action']).start()
    return bridge.journal.get(key)


def confirmed(runtime, verify, job):
    if job['body'].get('discovery') is not None:
        selection = {**job['selector'], 'id': job['body']['pluginId'], 'name': job['selector']['pluginName'], 'marketplaceName': job['marketplaceName'], 'marketplacePath': job['marketplacePath'], 'source': job['sourceIdentity']}
        detail = detail_for(runtime, selection, verify)
        plugin = {**selection, **detail['summary']}
    else: plugin = find(runtime, job['cwd'], job['body']['pluginId'], verify)
    if plugin['installed'] != (job['body']['action'] == 'install'): raise IPCError('原生插件安装状态尚未确认', uncertain=True)
    if selector(plugin) != job.get('selector') or plugin.get('source') != job.get('sourceIdentity'): raise IPCError('插件安装来源已改变', uncertain=True)
    return {'threadId': job['threadId'], 'pluginId': plugin['id'], 'installed': plugin['installed'], 'enabled': plugin['enabled'], 'authPolicy': plugin.get('authPolicy'), 'appsNeedingAuth': job.get('appsNeedingAuth')}


def run(bridge, ipc, generation, job, authorize):
    sent = replied = False
    try:
        with reader(bridge) as (runtime, verify):
            plugin = find(runtime, job['cwd'], job['body']['pluginId'], verify, job['body'].get('discovery')); action = job['body']['action']
            if action == 'install' and (plugin['installed'] or plugin.get('installPolicy') not in ('AVAILABLE', 'INSTALLED_BY_DEFAULT') or plugin.get('availability', 'AVAILABLE') != 'AVAILABLE'): raise IPCError('插件已安装或当前不可安装')
            if action == 'uninstall' and not plugin['installed']: raise IPCError('插件尚未安装')
            job = {**job, 'selector': selector(plugin), 'sourceIdentity': plugin.get('source'), 'marketplaceName': plugin['marketplaceName'], 'marketplacePath': plugin['marketplacePath']}
            def guarded(write):
                nonlocal sent
                with bridge.lock:
                    verify(); bridge.check_generation(ipc, generation)
                    if authorize: authorize()
                    if configuration_cwd(bridge, job['threadId']) != job['cwd']: raise IPCError('插件所属项目已改变')
                    bridge.journal.update(job['id'], state='dispatching', selector=job['selector'], sourceIdentity=job['sourceIdentity'], marketplaceName=job['marketplaceName'], marketplacePath=job['marketplacePath']); sent = True; write()
            params = {**job['selector'], 'installAttemptId': job['id']} if action == 'install' else {'pluginId': plugin['id']}
            response = runtime.rpc('plugin/' + action, params, guarded); replied = True; verify()
            if action == 'install':
                if not isinstance(response, dict) or response.get('authPolicy') not in ('ON_INSTALL', 'ON_USE') or not isinstance(response.get('appsNeedingAuth'), list): raise IPCError('插件安装回执不匹配', uncertain=True)
                job['appsNeedingAuth'] = response['appsNeedingAuth']
            result = confirmed(runtime, verify, job)
            with bridge.lock:
                verify(); bridge.check_generation(ipc, generation)
                if authorize: authorize()
                if configuration_cwd(bridge, job['threadId']) != job['cwd']: raise IPCError('插件所属项目已改变')
                bridge.journal.update(job['id'], state='completed', result=result, error=None, evidence='native-plugin-' + action)
    except Exception as error:
        uncertain = sent and (replied or not isinstance(error, IPCError) or error.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(error))
    finally: bridge.notify()


def recover(bridge, job):
    if not job.get('selector') or configuration_cwd(bridge, job['threadId']) != job['cwd']: return job
    with reader(bridge) as (runtime, verify):
        try: result = confirmed(runtime, verify, job)
        except IPCError: return job
        with bridge.lock:
            verify()
            if configuration_cwd(bridge, job['threadId']) != job['cwd']: return job
            return bridge.journal.update(job['id'], expected=job, state='completed', result=result, error=None, evidence='native-plugin-confirmed')
