"""Native skill inventory and validated structured selections."""
from pathlib import Path
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.reference_icons import skill_icons


def selections(value):
    if value is None: return []
    if not isinstance(value, list) or len(value) > 20: raise ValueError('最多选择 20 项技能')
    result = []
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'name', 'path'}
                or not isinstance(item['name'], str) or not 0 < len(item['name']) <= 200
                or not isinstance(item['path'], str) or not 0 < len(item['path']) <= 4096
                or not Path(item['path']).is_absolute() or '\x00' in item['path']):
            raise ValueError('技能选择无效')
        if item in result: raise ValueError('技能选择重复')
        result.append(dict(item))
    return result


def inputs(value):
    return [{'type': 'skill', **item} for item in selections(value)]


def inventory(runtime, tid):
    state = runtime.current(tid)
    if not state or state.get('_metadataOnly') or not runtime.connected:
        raise IPCError('技能发现需要已加载的原生会话')
    cwd = state.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).is_absolute(): raise IPCError('会话工作目录无效')
    identity = (runtime.process, runtime.session_id, cwd)
    result = catalog(runtime, cwd)
    verify(runtime, tid, identity)
    return result, identity


def catalog(runtime, cwd):
    result = runtime.rpc('skills/list', {'cwds': [cwd], 'forceReload': True})
    rows = [row for row in result['data'] if row['cwd'] == cwd]
    if len(rows) != 1: raise IPCError('原生技能列表工作目录不匹配')
    return {'cwd': cwd, 'skills': rows[0]['skills'], 'errors': rows[0]['errors']}


def verify(runtime, tid, identity):
    state = runtime.current(tid)
    if (not runtime.connected or not state or state.get('_metadataOnly')
            or (runtime.process, runtime.session_id, state.get('cwd')) != identity):
        raise IPCError('技能所属会话或工作目录已改变')


def guard_inputs(runtime, tid, native_input, before_send=None):
    from carryon.sessions.mentions import guard_inputs as guard_mentions
    before_send = guard_mentions(runtime, tid, native_input, before_send)
    requested = selections([{k: v for k, v in item.items() if k != 'type'}
                            for item in native_input if item.get('type') == 'skill'])
    if not requested: return before_send
    discovered, identity = inventory(runtime, tid)
    enabled = {(item['name'], item['path']) for item in discovered['skills'] if item['enabled']}
    if any((item['name'], item['path']) not in enabled for item in requested):
        raise IPCError('所选技能已禁用或不属于当前工作目录，请刷新')
    def guarded(write):
        def checked():
            with runtime.lock:
                verify(runtime, tid, identity)
                write()
        if before_send: before_send(checked)
        else: checked()
    return guarded


def discover_runtime(bridge, tid):
    bridge.assert_target(tid)
    ipc, generation = bridge.require()
    runtime = ipc if getattr(ipc, 'protocol', None) == 'codex-app-server' else None
    service = getattr(bridge, 'owner_service', None)
    if runtime is None and service is not None:
        with service.lock:
            entry = service.entries.get(tid)
            if entry and not any(entry.get(k) for k in ('suspended', 'conflict', 'disconnect')):
                runtime = entry['runtime']
    if runtime is None: raise IPCError('当前桌面会话不支持原生技能发现')
    return runtime, ipc, generation


def discover(bridge, tid):
    runtime, ipc, generation = discover_runtime(bridge, tid)
    result, identity = inventory(runtime, tid)
    result = {**result, 'skills': skill_icons(result['skills'])}
    verify(runtime, tid, identity)
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        bridge.assert_target(tid)
    return result
