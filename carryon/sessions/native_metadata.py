"""Eligibility for persistent native metadata controls."""
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.subagents import is_subagent

def record(bridge, tid):
    row = bridge.catalog.archive_record(tid)
    if is_subagent(row):
        raise IPCError('子会话不支持独立管理')
    if row.get('history_mode') != 'paginated':
        raise IPCError('此会话不支持原生持久管理')
    return row


def supported(bridge):
    return getattr(bridge.ipc, 'protocol', None) == 'codex-app-server' or hasattr(bridge, 'owners')



def configuration_cwd(bridge, tid):
    from pathlib import Path
    row = record(bridge, tid); cwd = row.get('cwd')
    if row.get('archived') or not isinstance(cwd, str) or not Path(cwd).is_absolute(): raise IPCError('配置需要有效的未归档项目会话')
    return cwd


def configuration_busy(bridge):
    return any(job['kind'] in ('skill-config', 'plugin-install', 'plugin-uninstall') and job['state'] in ('preparing', 'dispatching', 'uncertain') for job in bridge.journal.list())
