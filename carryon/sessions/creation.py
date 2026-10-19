"""Create project threads in a temporary app-server owned for the task lifetime."""
import json
import re
import threading
import time
import uuid
from pathlib import Path

from carryon.contracts import digest, text, validate_request_id
from carryon.errors import BridgeError
from carryon.errors import IPCError
from carryon.workspaces.workspace import project_identity


def resolve_project(catalog, project_id):
    if not isinstance(project_id, str) or not re.fullmatch(r'[0-9a-f]{64}', project_id):
        raise ValueError('请选择一个项目')
    state = json.loads((catalog.home / '.codex-global-state.json').read_text())
    matches = []
    for native_id, project in state.get('local-projects', {}).items():
        roots = project.get('rootPaths', [])
        if roots and project_identity(roots[0], native_id=native_id)[0] == project_id:
            matches.append({'id': native_id, 'cwd': str(Path(roots[0]).expanduser().absolute()), 'groupId': project_id})
    if len(matches) != 1:
        raise BridgeError('此项目的 Codex 归属无法确认，请在桌面端重新选择项目', 409)
    project = matches[0]
    if not Path(project['cwd']).is_dir():
        raise BridgeError('项目目录已不可用，请在 Codex 重新选择项目', 409)
    return project


def submit(bridge, request_id, prompt, project_id, source=None, authorize=None, images=None, settings=None, skills=None, mentions=None):
    from carryon.sessions.images import validate_images
    images = validate_images(images)
    from carryon.sessions.creation_settings import validate
    settings = validate(settings)
    from carryon.sessions.skills import selections as skill_selections
    from carryon.sessions.mentions import selections as mention_selections
    skills, mentions = skill_selections(skills), mention_selections(mentions)
    prompt = text(prompt, allow_empty=bool(images or skills or mentions))
    validate_request_id(request_id)
    fingerprint = digest(['owner-create', project_id, prompt, images, settings, skills, mentions])
    ipc, generation = bridge.require()
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        if authorize: authorize()
        previous = bridge.journal.get(request_id)
        if previous:
            if previous.get('fingerprint') != fingerprint:
                raise BridgeError('requestId 已用于不同内容')
            return previous
        project = resolve_project(bridge.catalog, project_id)
        service = bridge.owners()
        job = {'id': request_id, 'kind': 'create', 'threadId': '', 'state': 'preparing',
               'created': time.time(), 'fingerprint': fingerprint, 'creationProject': project,
               'clientMessageId': str(uuid.uuid4()), 'creationSettings': settings, 'skills': skills, 'mentions': mentions, **(source or {})}
        bridge.journal.insert(job)
    threading.Thread(target=dispatch, args=(bridge, ipc, generation, service, job, prompt, authorize, images),
                     daemon=True, name='owner-create').start()
    return bridge.journal.get(request_id)


def dispatch(bridge, ipc, generation, service, job, prompt, authorize, images=None):
    runtime = None
    tid = None
    adopted = False
    created_sent = False
    turn_sent = False
    project = job['creationProject']
    def check():
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if authorize: authorize()
            if resolve_project(bridge.catalog, project['groupId']) != project:
                raise BridgeError('目标项目已改变，请重新选择项目')
    def create_write(write):
        nonlocal created_sent
        with bridge.lock:
            check()
            bridge.journal.update(job['id'], state='dispatching')
            created_sent = True
            write()
    def turn_write(write):
        nonlocal turn_sent
        with bridge.lock:
            check()
            turn_sent = True
            write()
    try:
        check()
        runtime = service.runtime_factory(bridge.catalog.home,
            runtime_directory=service.directory / 'creations' / job['id'])
        runtime.connect()
        runtime.require_account()
        thread = runtime.create_thread({'cwd': project['cwd'], 'projectId': project['id'],
                                        'historyMode': 'paginated'}, create_write)
        from carryon.sessions.catalog import valid_id
        tid = valid_id(thread['id'])
        bridge.journal.update(job['id'], threadId=tid, createdThreadId=tid)
        if (thread.get('projectId') != project['id'] or Path(thread.get('cwd', '')).resolve() != Path(project['cwd']).resolve() or
                thread.get('historyMode') != 'paginated'):
            raise IPCError('原生创建结果与目标项目不符，未投递任务')
        from carryon.sessions.creation_settings import apply
        apply(runtime, tid, job.get('creationSettings'), turn_write)
        owner = service.adopt(tid, runtime, check)['owner']
        adopted = True
        check()
        discovered, _ = ipc.snapshot(tid)
        if discovered != owner: raise IPCError('创建后的会话 owner 已改变，未投递任务')
        turn = ipc.start(tid, prompt, owner, job['clientMessageId'], turn_write, images=images, **({'skills': job['skills']} if job.get('skills') else {}), **({'mentions': job['mentions']} if job.get('mentions') else {}))
        bridge.journal.update(job['id'], state='completed', turnId=turn['id'],
                              evidence='app-server-create-owner-start')
        bridge.notify()
    except Exception as exc:
        # Once creation may have happened, preserve the receipt and never create again.
        uncertain = bool(tid) or created_sent and (not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
        # An uncertain start may still be running; only known pre-delivery failures
        # can release the newly adopted runtime safely here.
        if adopted and (not turn_sent or isinstance(exc, IPCError) and not exc.uncertain):
            try: service.release(tid)
            except IPCError: pass
    finally:
        if runtime is not None and not adopted: runtime.close()
