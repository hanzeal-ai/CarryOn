"""Canonical installed-plugin and accessible-app references from the native runtime."""
from pathlib import Path
from carryon.errors import IPCError


def selections(value):
    if value is None: return []
    if not isinstance(value, list) or len(value) > 20: raise ValueError('最多选择 20 项插件或应用')
    result = []
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'name', 'path'}
                or not isinstance(item['name'], str) or not 0 < len(item['name']) <= 200
                or not isinstance(item['path'], str) or not 0 < len(item['path']) <= 4096
                or not item['path'].startswith(('plugin://', 'app://'))
                or not item['path'].split('://', 1)[1] or any(c.isspace() or ord(c) < 32 for c in item['path'])):
            raise ValueError('插件或应用引用无效')
        if item in result: raise ValueError('插件或应用引用重复')
        result.append(dict(item))
    return result


def inputs(value):
    return [{'type': 'mention', **item} for item in selections(value)]


def inventory(runtime, tid, *, plugins=True, apps=True, strict=False):
    from carryon.sessions.skills import verify
    state = runtime.current(tid)
    if not state or state.get('_metadataOnly') or not runtime.connected:
        raise IPCError('引用发现需要已加载的原生会话')
    cwd = state.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).is_absolute(): raise IPCError('会话工作目录无效')
    identity = (runtime.connection_identity, cwd)
    result = catalog(runtime, cwd, tid, plugins=plugins, apps=apps, strict=strict)
    verify(runtime, tid, identity)
    return result, identity


def catalog(runtime, cwd, tid=None, *, plugins=True, apps=True, strict=False):
    rows, errors = [], []
    if plugins:
        try:
            result = runtime.rpc('plugin/installed', {'cwds': [cwd]})
            errors.extend(result.get('marketplaceLoadErrors', []))
            for marketplace in result['marketplaces']:
                for plugin in marketplace['plugins']:
                    if not plugin['installed']: continue
                    rows.append({'name': plugin['name'], 'path': 'plugin://' + plugin['id'].strip(), 'kind': 'plugin',
                        'description': (plugin.get('interface') or {}).get('shortDescription') or '',
                        'enabled': plugin['enabled'] and plugin.get('availability', 'AVAILABLE') == 'AVAILABLE'})
        except IPCError as exc:
            if strict: raise
            errors.append({"source": "plugins", "message": str(exc)})
    if apps:
        try:
            cursor, seen = None, set()
            while True:
                result = runtime.rpc('app/list', {'threadId': tid, 'cursor': cursor, 'limit': 100, 'forceRefetch': True})
                rows.extend({'name': app['name'], 'path': 'app://' + app['id'], 'kind': 'app',
                             'description': app.get('description') or '',
                             'enabled': app.get('isAccessible', False) and app.get('isEnabled', True)} for app in result['data'])
                cursor = result.get('nextCursor')
                if not cursor: break
                if cursor in seen or len(rows) > 10000: raise IPCError('应用目录分页异常')
                seen.add(cursor)
        except IPCError as exc:
            if strict: raise
            errors.append({"source": "apps", "message": str(exc)})
    unique = {}
    for row in rows:
        previous = unique.get(row['path'])
        if previous is not None and previous != row: raise IPCError('原生引用目录存在冲突身份')
        unique[row['path']] = row
    return {'mentions': list(unique.values()), 'errors': errors}


def guard_inputs(runtime, tid, native_input, before_send=None):
    requested = selections([{k: v for k, v in item.items() if k != 'type'}
                            for item in native_input if item.get('type') == 'mention'])
    if not requested: return before_send
    result, identity = inventory(runtime, tid, plugins=any(i['path'].startswith('plugin://') for i in requested),
                                  apps=any(i['path'].startswith('app://') for i in requested), strict=True)
    enabled = {(row['name'], row['path']) for row in result['mentions'] if row['enabled']}
    if any((item['name'], item['path']) not in enabled for item in requested):
        raise IPCError('所选插件或应用已禁用或不可访问，请刷新')
    def guarded(write):
        def checked():
            from carryon.sessions.skills import verify
            with runtime.lock:
                verify(runtime, tid, identity)
                write()
        if before_send: before_send(checked)
        else: checked()
    return guarded


def discover(bridge, tid):
    from carryon.sessions.skills import discover_runtime
    runtime, ipc, generation = discover_runtime(bridge, tid)
    result, _ = inventory(runtime, tid)
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        bridge.assert_target(tid)
    return result
