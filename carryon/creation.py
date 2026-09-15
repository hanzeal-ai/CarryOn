"""Select a project's idle native conversation without changing the shared controller."""
import json
import re
import time
from pathlib import Path

from .contracts import digest
from .errors import BridgeError
from .ipc import IPCError
from .workspace import project_identity


def resolve_project(catalog, project_id):
    if not isinstance(project_id, str) or not re.fullmatch(r'[0-9a-f]{64}', project_id):
        raise ValueError('请选择一个项目')
    state = json.loads((catalog.home / '.codex-global-state.json').read_text())
    matches = []
    for native_id, project in state.get('local-projects', {}).items():
        for root in project.get('rootPaths', []):
            if project_identity(root)[0] == project_id:
                matches.append({'id': native_id, 'cwd': str(Path(root).expanduser().absolute()), 'groupId': project_id})
    if len(matches) != 1:
        raise BridgeError('此项目的 Codex 归属无法确认，请在桌面端重新选择项目', 409)
    return matches[0]


def belongs(row, project):
    return project_identity(row.get('projectRoot', row.get('projectKey', row.get('cwd'))), row.get('projectless', False))[0] == project['groupId']


def submit(bridge, request_id, prompt, project_id, source=None, authorize=None):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
        raise ValueError('请输入 1–16000 字符的消息')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
        raise ValueError('requestId 无效')
    fingerprint = digest([project_id, prompt.strip()])
    ipc, generation = bridge.require()
    if authorize: authorize()
    previous = bridge.journal.get(request_id)
    if previous:
        if previous.get('projectRequestFingerprint') != fingerprint:
            raise BridgeError('requestId 已用于不同内容')
        return previous
    project = resolve_project(bridge.catalog, project_id)
    candidates = [row for row in bridge.catalog.list(2147483647) if belongs(row, project)]
    candidates.sort(key=lambda row: ipc.current(row['id']) is None)
    deadline = time.monotonic() + 15
    from .bridge import idle_snapshot
    for row in candidates:
        if time.monotonic() >= deadline: break
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if authorize: authorize()
            if any(job['threadId'] == row['id'] and job['state'] in ('preparing', 'dispatching', 'accepted', 'uncertain') for job in bridge.journal.list()):
                continue
        try:
            bridge.assert_target(row['id'])
            state = ipc.current(row['id'])
            if state is None: _, state = ipc.sidebar_snapshot(row['id'])
            idle_snapshot(state)
        except (ValueError, IPCError, BridgeError):
            continue
        return bridge.submit('create', request_id, prompt, row['id'], source={**(source or {}), 'projectRequestFingerprint': fingerprint},
                             authorize=authorize, creation_project=project)
    raise BridgeError('项目中未找到可用的空闲会话，请在 Codex 打开该项目的一个会话后重试', 409)
