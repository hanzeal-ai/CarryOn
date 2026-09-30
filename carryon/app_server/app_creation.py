"""Create directly in the workspace-owned app-server, without a controller task."""
import threading
import time
import uuid

from carryon.contracts import digest, text, validate_request_id
from carryon.errors import BridgeError
from carryon.desktop_ipc.ipc import IPCError
from carryon.paths import private_dir
from carryon.workspaces.workspace import project_identity


def submit(bridge, request_id, prompt, project_id=None, source=None, authorize=None):
    prompt = text(prompt)
    validate_request_id(request_id)
    ipc, generation = bridge.require()
    ipc.require_account()
    if project_id not in (None, project_identity(None)[0]):
        raise BridgeError('请在此工作区选择无项目会话；项目会话可在该工作区的 Codex CLI 中创建', 409)
    fingerprint = digest(['app-server-create', project_id, prompt])
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        previous = bridge.journal.get(request_id)
        if previous:
            if previous['fingerprint'] != fingerprint: raise BridgeError('requestId 已用于不同内容')
            return previous
        job = {'id': request_id, 'kind': 'create', 'threadId': '', 'state': 'preparing',
               'created': time.time(), 'fingerprint': fingerprint, 'clientMessageId': str(uuid.uuid4()), **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=dispatch, args=(bridge, ipc, generation, job, prompt, authorize), daemon=True).start()
    return job


def dispatch(bridge, ipc, generation, job, prompt, authorize):
    sent = False
    try:
        def guarded(write):
            nonlocal sent
            with bridge.lock:
                bridge.check_generation(ipc, generation)
                if authorize: authorize()
                bridge.journal.update(job['id'], state='dispatching')
                sent = True
                write()
        cwd = private_dir(bridge.workspace_directory / 'tasks' / job['id'])
        result = ipc.rpc('thread/start', {'cwd': str(cwd)}, before_send=guarded)
        tid = result['thread']['id']
        bridge.journal.update(job['id'], threadId=tid, createdThreadId=tid)
        turn = ipc.start(tid, prompt, 'app-server', job['clientMessageId'], guarded)
        bridge.journal.update(job['id'], state='accepted', turnId=turn['id'], evidence='app-server-thread-start-and-turn-start')
        bridge.workspace.catalog_refresh()
        bridge.notify()
    except Exception as exc:
        # Once a thread exists, a later refusal still needs review, never a retry
        # that silently creates a second task.
        existing = bridge.journal.get(job['id']) or {}
        uncertain = bool(existing.get('createdThreadId')) or sent and (not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
