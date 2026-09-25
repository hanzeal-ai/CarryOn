"""Select a recent idle native conversation without changing the shared controller."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from .contracts import digest
from .errors import BridgeError
from .ipc import IPCError
from .workspace import project_identity, row_project_identity


def is_git_repository(root):
    if not Path(root).is_dir():
        raise BridgeError('项目目录已不可用，请在 Codex 重新选择项目', 409)
    try:
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--is-inside-work-tree'],
                                capture_output=True, text=True, timeout=3, env=dict(os.environ, LC_ALL='C'))
    except (OSError, subprocess.SubprocessError):
        raise BridgeError('无法确认项目 Git 状态，请稍后重试', 409) from None
    if result.returncode == 0 and result.stdout.strip() in ('true', 'false'):
        return result.stdout.strip() == 'true'
    if result.returncode == 128 and 'not a git repository' in result.stderr:
        return False
    raise BridgeError('无法确认项目 Git 状态，请稍后重试', 409)


def resolve_project(catalog, project_id):
    if not isinstance(project_id, str) or not re.fullmatch(r'[0-9a-f]{64}', project_id):
        raise ValueError('请选择一个项目')
    state = json.loads((catalog.home / '.codex-global-state.json').read_text())
    matches = []
    for native_id, project in state.get('local-projects', {}).items():
        roots = project.get('rootPaths', [])
        if roots and project_identity(roots[0], native_id=native_id)[0] == project_id:
            matches.append({'id': native_id, 'cwd': str(Path(roots[0]).expanduser().absolute()), 'groupId': project_id})
            continue
        # Previously released clients can hold directory IDs in their display cache.
        # Accept them only when they still identify exactly one native project.
        for root in project.get('rootPaths', []):
            if project_identity(root)[0] == project_id:
                matches.append({'id': native_id, 'cwd': str(Path(root).expanduser().absolute()), 'groupId': project_id})
                break
    if len(matches) != 1:
        raise BridgeError('此项目的 Codex 归属无法确认，请在桌面端重新选择项目', 409)
    project = matches[0]
    project['isGitRepository'] = is_git_repository(project['cwd'])
    return project


def belongs(row, project):
    if row.get('projectless'):
        return False
    if row.get('nativeProjectId'):
        return row['nativeProjectId'] == project['id']
    return row_project_identity(row)[0] == project['groupId']


def validate_controller(catalog, thread_id, project):
    # The target project is independent of the conversation borrowing its turn.
    if resolve_project(catalog, project['groupId']) != project:
        raise BridgeError('目标项目已改变，请重新选择项目')
    if not any(row['id'] == thread_id for row in catalog.list(2147483647)):
        raise BridgeError('控制会话已不可用，请重试')


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
    candidates = bridge.catalog.list(2147483647)
    # Catalog order is newest first; prefer the projectless Recent group.
    candidates.sort(key=lambda row: (not row.get('projectless', False), -row.get('updated_at', 0)))
    group, deadline = None, 0
    from .bridge import idle_snapshot
    for row in candidates:
        recent = bool(row.get('projectless', False))
        if recent != group:
            group, deadline = recent, time.monotonic() + 15
        if time.monotonic() >= deadline: continue
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if authorize: authorize()
            if any(job['threadId'] == row['id'] and job['state'] in ('preparing', 'dispatching', 'accepted', 'uncertain') for job in bridge.journal.list()):
                continue
        try:
            bridge.assert_target(row['id'])
            state = ipc.current(row['id'])
            if state is None:
                try: _, state = ipc.sidebar_snapshot(row['id'])
                except IPCError: state = None
            if state is None or (state.get('threadRuntimeStatus') or {}).get('type') == 'notLoaded':
                def before_open():
                    with bridge.lock:
                        bridge.check_generation(ipc, generation)
                        if authorize: authorize()
                        validate_controller(bridge.catalog, row['id'], project)
                        bridge.assert_target(row['id'])
                _, state = ipc.wake_snapshot(row['id'], before_open=before_open)
            idle_snapshot(state)
        except (ValueError, IPCError, BridgeError):
            continue
        return bridge.submit('create', request_id, prompt, row['id'], source={**(source or {}), 'projectRequestFingerprint': fingerprint},
                             authorize=authorize, creation_project=project)
    raise BridgeError('最近及其他会话中未找到可用的空闲会话，请在 Codex 打开一个空闲会话后重试', 409)
