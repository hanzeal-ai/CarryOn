"""Bounded adapters for the verified desktop follower method contract."""
import time
import uuid
from contextlib import nullcontext

from carryon.desktop_ipc.ipc import IPCError
from carryon.contracts import digest, text
from carryon.contracts import settings as validate_settings, approval, approval_choices, validate, SCHEMAS
from carryon.sessions.queue import transform, message as queued_message
from carryon.sessions.thread_status import project_status

METHODS = {
    'interrupt': ('interrupt-turn', 4), 'steer': ('steer-turn', 1),
    'compact': ('compact-thread', 1), 'settings': ('update-thread-settings', 2),
    'edit': ('edit-last-user-turn', 2), 'resume': ('start-turn', 2), 'clear-queue': ('set-queued-follow-ups-state', 1),
    'command-approval': ('command-approval-decision', 1),
    'file-approval': ('file-approval-decision', 1),
    'permissions-approval': ('permissions-request-approval-response', 1),
    'user-input': ('submit-user-input', 1),
    'mcp-response': ('submit-mcp-server-elicitation-response', 1),
}
QUEUE_ACTIONS = {'queue-add', 'queue-edit', 'queue-delete', 'queue-reorder', 'queue-resume', 'clear-queue'}
for _action in QUEUE_ACTIONS:
    METHODS[_action] = ('set-queued-follow-ups-state', 1)

REQUEST_METHODS = {
    'command-approval': 'item/commandExecution/requestApproval',
    'file-approval': 'item/fileChange/requestApproval',
    'permissions-approval': 'item/permissions/requestApproval',
    'user-input': 'item/tool/requestUserInput',
    'mcp-response': 'mcpServer/elicitation/request',
}


def turns(state):
    history = state.get('turnHistory', {})
    if history.get('kind') != 'canonical':
        return state.get('turns', [])
    history = history.get('history', {})
    entities, result, seen = history.get('entitiesByKey', {}), [], set()
    for island in history.get('islands', []):
        for entry in island.get('entries', []):
            key = entry.get('value')
            if isinstance(key, str) and key in entities and key not in seen:
                result.append(entities[key]); seen.add(key)
    return result


def controls(state):
    items = turns(state)
    active = next((t for t in reversed(items) if t.get('status') == 'inProgress'), None)
    reviewing = active is not None and any(item.get('type') == 'enteredReviewMode' for item in active.get('items', []))
    last = items[-1] if items else {}
    user = next((item for item in reversed(last.get('items', [])) if item.get('type') == 'userMessage'), None)
    inputs = user.get('content', []) if user is not None else last.get('params', {}).get('input', [])
    text = '\n'.join(part.get('text', '') for part in inputs if part.get('type') == 'text')
    requests = []
    for r in state.get('requests', []):
        if not isinstance(r, dict):
            continue
        action = next((a for a, m in REQUEST_METHODS.items() if m == r.get('method')), None)
        if action:
            requests.append({'id': r.get('id'), 'action': action, 'method': r['method'],
                             'fingerprint': digest(r), 'params': r.get('params', {}),
                             'decisions': approval_choices(action, r.get('params', {}))})
    writable = set(SCHEMAS['settings']['properties']) - {'threadId', 'multiAgentMode'}
    current_settings = {k: v for k, v in (state.get('latestThreadSettings') or {}).items() if k in writable}
    if 'collaborationMode' not in current_settings and state.get('latestCollaborationMode') is not None:
        current_settings['collaborationMode'] = state['latestCollaborationMode']
    # Desktop follower operations come from this pinned contract; app-server advertises its own set.
    return {'supportedOperations': state.get('supportedOperations', sorted(METHODS)),
            'supportsMentions': state.get('supportsMentions') is True and not state.get('_metadataOnly') and state.get('threadRuntimeStatus', {}).get('type') in ('idle', 'active'),
            'supportsFileReferences': state.get('supportsFileReferences') is True and not state.get('_metadataOnly') and state.get('threadRuntimeStatus', {}).get('type') in ('idle', 'active'),
            'supportsSkills': state.get('supportsSkills') is True and not state.get('_metadataOnly') and state.get('threadRuntimeStatus', {}).get('type') in ('idle', 'active'),
            'supportsGoal': state.get('supportsGoal') is True and not state.get('_metadataOnly') and state.get('threadRuntimeStatus', {}).get('type') in ('idle', 'active'),
            'supportsBackgroundTerminals': state.get('supportsBackgroundTerminals') is True and not state.get('_metadataOnly') and state.get('threadRuntimeStatus', {}).get('type') in ('idle', 'active'),
            'goal': state.get('threadGoal'), 'goalUnknown': state.get('_goalUnknown', False),
            'supportedSettings': sorted(writable.intersection(state.get('supportedSettings', writable))),
            'activeTurnId': active.get('turnId') if active else None,
            'activeTurnKind': 'review' if reviewing else None, 'canSteer': active is not None and not reviewing,
            'lastTurnId': last.get('turnId'), 'lastTurnStatus': last.get('status'), 'lastUserText': text,
            'settings': current_settings, 'requests': requests}


def build(action, data, state):
    from carryon.sessions.skills import selections, inputs
    skills = selections(data.get('skills'))
    from carryon.sessions.mentions import selections as mention_selections, inputs as mention_inputs
    mentions = mention_selections(data.get('mentions'))
    if mentions and (action not in ('steer', 'queue-add') or not state.get('supportsMentions')):
        raise ValueError('当前操作不支持插件或应用引用')
    if skills and (action not in ('steer', 'queue-add') or not state.get('supportsSkills')):
        raise ValueError('当前操作不支持技能选择')
    if action not in METHODS:
        raise ValueError('不支持的会话操作')
    from carryon.sessions.file_references import selections as file_selections, project
    files = file_selections(data.get('files'))
    if files and (action not in ('steer', 'queue-add') or not state.get('supportsFileReferences')):
        raise ValueError('当前操作不支持项目文件引用')
    if files:
        data = {**data, 'prompt': project(text(data.get('prompt'), allow_empty=True), files)}
    c = controls(state)
    runtime = state.get('threadRuntimeStatus', {}).get('type')
    params = {'conversationId': state['id']}
    if action in ('interrupt', 'steer'):
        if runtime != 'active' or not c['activeTurnId'] or data.get('expectedTurnId') != c['activeTurnId']:
            raise ValueError('执行轮次已改变，请刷新后操作')
        if action == 'interrupt':
            params.update(mode='user-stop', expectedTurnId=c['activeTurnId'])
        else:
            if not c['canSteer']: raise ValueError('当前原生审查轮不支持立即补充，请使用排队')
            from carryon.sessions.images import validate_images
            images = validate_images(data.get('images'))
            prompt = data.get('prompt')
            prompt = text(prompt, allow_empty=bool(images or skills or mentions))
            params.update(input=([{'type': 'text', 'text': prompt, 'text_elements': []}] if prompt else []) + [{'type': 'image', 'url': url} for url in images] + inputs(skills) + mention_inputs(mentions),
                          clientUserMessageId=str(uuid.uuid4()), attachments=[],
                          restoreMessage=queued_message(prompt, state, images, skills, mentions))
    elif action in QUEUE_ACTIONS:
        if runtime not in ('active', 'idle'):
            raise ValueError('会话运行状态尚未确认')
        params['state'] = {state['id']: transform(action, data, state, state['nativeQueue'])}
        if state.get('queueBackend') == 'app-server': params['expectedQueueFingerprint'] = data['queueFingerprint']
    elif action == 'settings':
        if runtime not in ('active', 'idle'):
            raise ValueError('会话运行状态尚未确认')
        params['threadSettings'] = validate_settings(data.get('settings'), state['id'])
    elif action in ('compact', 'edit', 'resume'):
        if project_status(state)['state'] != 'idle':
            raise ValueError('此操作需要已确认空闲且没有待处理请求的会话')
        if action in ('edit', 'resume'):
            if action == 'resume' and (c['lastTurnStatus'] != 'interrupted' or not c['lastTurnId']):
                raise ValueError('只有已暂停的最后一轮可以继续执行')
            if data.get('turnId') != c['lastTurnId'] or (action == 'edit' and not c['lastUserText']):
                raise ValueError('最后一轮已改变或不支持文本编辑')
            if action == 'edit' and data.get('confirmed') is not True:
                raise ValueError('编辑会替换最后一轮并重新执行，请确认')
            if action == 'resume':
                # Native startEmptyTurn continues the retained history with empty input.
                # Editing would first revert/roll back the interrupted user turn.
                params['turnStart'] = {'request': {'threadId': state['id'], 'input': []},
                                       'context': {'inheritThreadSettings': True}}
            else:
                params.update(turnId=c['lastTurnId'], message=text(data.get('prompt')),
                              shouldSendPermissionOverrides=False)
    else:
        request = next((r for r in state.get('requests', [])
                        if type(r.get('id')) is type(data.get('nativeRequestId'))
                        and r.get('id') == data.get('nativeRequestId')
                        and r.get('method') == REQUEST_METHODS[action]), None)
        if request is None or digest(request) != data.get('requestFingerprint'):
            raise ValueError('待处理请求已改变或已被处理，请刷新后重试')
        params['requestId'] = request['id']
        if action in ('command-approval', 'file-approval'):
            params['decision'] = approval(action, data.get('decision'), request.get('params', {}))
        elif action == 'permissions-approval':
            if 'response' in data:
                response = data['response']
            else:
                if data.get('decision') not in ('accept', 'decline'):
                    raise ValueError('请选择允许或拒绝')
                permissions = request.get('params', {}).get('permissions')
                if data['decision'] == 'accept' and not isinstance(permissions, dict):
                    raise ValueError('无法识别原生权限范围，请在 App 处理')
                response = {'permissions': permissions if data['decision'] == 'accept' else {},
                            'scope': data.get('scope', 'turn')}
            validate(response, SCHEMAS['permissions'])
            if not permission_subset(response['permissions'], request.get('params', {}).get('permissions', {})):
                raise ValueError('授予的权限超出当前请求范围')
            params['response'] = response
        elif action == 'user-input':
            answers = data.get('answers')
            questions = request.get('params', {}).get('questions', [])
            ids = {q['id'] for q in questions}
            if not isinstance(answers, dict) or set(answers) != ids:
                raise ValueError('请回答当前请求的全部问题')
            for values in answers.values():
                if not isinstance(values, list) or not values or any(not isinstance(v, str) or len(v) > 16000 for v in values):
                    raise ValueError('每题答案必须是非空字符串数组')
            params['response'] = {'answers': {k: {'answers': v} for k, v in answers.items()}}
        elif action == 'mcp-response':
            response = data.get('response')
            if not isinstance(response, dict) or response.get('action') not in ('accept', 'decline', 'cancel') or set(response) - {'action', 'content'}:
                raise ValueError('MCP response 必须包含 action，可附带 content')
            if response.get('content') is not None and not isinstance(response['content'], dict):
                raise ValueError('MCP content 必须为对象')
            params['response'] = response
    method, version = METHODS[action]
    return 'thread-follower-' + method, version, params


def permission_subset(granted, requested):
    if granted is None or granted is False:
        return True
    if isinstance(granted, dict):
        return isinstance(requested, dict) and all(permission_subset(v, requested.get(k)) for k, v in granted.items())
    if isinstance(granted, list):
        return isinstance(requested, list) and all(v in requested for v in granted)
    return type(granted) is type(requested) and granted == requested


def submit(bridge, thread_id, data, source=None, authorize=None, prepared=None, parent_id=None, *, _reserved=None):
    from carryon.sessions.skills import selections
    from carryon.errors import BridgeError
    from carryon.sessions.catalog import valid_id
    valid_id(thread_id)
    if parent_id and (data.get('skills') or data.get('mentions') or data.get('files')): raise ValueError('临时聊天不支持技能、插件、应用或项目文件引用')
    bridge.assert_target(thread_id, parent_id)
    ipc, generation = bridge.require()
    action, request_id = data.get('action'), data.get('requestId')
    if hasattr(ipc, 'supported_operations') and action not in ipc.supported_operations:
        raise ValueError('此工作区不支持该操作')
    if action not in METHODS and action not in ('review', 'goal-set', 'goal-pause', 'goal-clear', 'voice-start', 'voice-stop'):
        raise ValueError('不支持的会话操作')
    from carryon.contracts import validate_request_id
    validate_request_id(request_id)
    fingerprint = digest([thread_id, data] + ([parent_id] if parent_id else []))
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        previous = bridge.journal.get(request_id)
        if previous and previous != _reserved:
            if previous['fingerprint'] != fingerprint:
                raise BridgeError('requestId 已用于不同内容')
            return bridge.refresh_job(request_id) if action in ('voice-start', 'voice-stop') and previous['state'] == 'uncertain' else previous
        for previous in bridge.journal.list():
            if previous['threadId'] != thread_id or previous['id'] == request_id:
                continue
            if action in QUEUE_ACTIONS and previous['kind'] in {'operation:' + a for a in QUEUE_ACTIONS} and previous['state'] in ('preparing', 'dispatching', 'uncertain'):
                raise BridgeError('原生队列写入尚未确认，请先核对队列；其他操作不受影响')
            if action in ('compact', 'edit', 'resume', 'review') and previous['kind'] in ('compose', 'message', 'create', 'operation:compact', 'operation:edit', 'operation:resume', 'operation:review') and previous['state'] in ('preparing', 'dispatching'):
                raise BridgeError('会话正在提交操作，请稍后重试')
        job = {'id': request_id, 'fingerprint': fingerprint, 'kind': 'operation:' + action,
               'threadId': thread_id, 'created': time.time(), 'state': 'preparing'}
        if source:job.update(source)
        if data.get('skills'): job['skills'] = selections(data['skills'])
        if data.get('mentions'):
            from carryon.sessions.mentions import selections as mention_selections
            job['mentions'] = mention_selections(data['mentions'])
        if data.get('files'):
            from carryon.sessions.file_references import selections as file_selections
            job['files'] = file_selections(data['files'])
        if parent_id is not None: job['sideParentId'] = parent_id
        if _reserved is None: bridge.journal.insert(job)
        else:
            if bridge.journal.get(request_id) != _reserved: raise BridgeError('发送准备记录已变化')
            job['created'] = _reserved['created']
            bridge.journal.update(request_id, **{k: v for k, v in job.items() if k != 'id'})
    dispatch(bridge, ipc, generation, job, data, authorize, prepared)
    return bridge.journal.get(request_id)


def dispatch(bridge, ipc, generation, job, data, authorize=None, prepared=None):
    if data['action'] in ('voice-start', 'voice-stop'):
        from carryon.app_server.realtime_voice import dispatch as voice
        voice(bridge, ipc, generation, job, data, authorize)
        return
    if data['action'] in ('goal-set', 'goal-pause', 'goal-clear'):
        from carryon.app_server.goals import dispatch as goal
        goal(bridge, ipc, generation, job, data, authorize)
        return
    if data['action'] == 'review':
        from carryon.app_server.review import dispatch as review
        review(bridge, ipc, generation, job, data, authorize)
        return
    if data['action'] == 'edit' and dispatch_native_edit(bridge, ipc, generation, job, data, authorize):
        return
    sent = False
    try:
        if prepared is not None and hasattr(ipc, 'current') and ipc.current(job['threadId']) is prepared[1]:
            owner, state = prepared
        else:
            owner, state = ipc.snapshot(job['threadId'])
        bridge.assert_target(job['threadId'], job.get('sideParentId'), state)
        if data['action'] in QUEUE_ACTIONS:
            state = {**state, 'nativeQueue': bridge.queue(job['threadId'], job.get('sideParentId'), authoritative=True)['messages']}
        method, version, params = build(data['action'], data, state)
        def guarded(write):
            nonlocal sent
            queue = bridge.queue(job['threadId'], job.get('sideParentId'), authoritative=True)['messages'] if data['action'] in QUEUE_ACTIONS else None
            with bridge.lock:
                bridge.check_generation(ipc, generation)
                if authorize:authorize()
                bridge.assert_target(job['threadId'], job.get('sideParentId'))
                # Recheck streamed state immediately before writing, when available.
                current = ipc.current(job['threadId']) if hasattr(ipc, 'current') else None
                if prepared is not None and current is None:
                    raise IPCError('会话状态正在重新同步，此请求未投递')
                if data['action'] in QUEUE_ACTIONS:
                    current = {**(current or state), 'nativeQueue': queue}
                if current is not None:
                    build(data['action'], data, current)
                bridge.journal.update(job['id'], state='dispatching')
                sent = True
                write()
        if data['action'] == 'steer':
            bridge.journal.update(job['id'], clientMessageId=params['clientUserMessageId'])
        elif data['action'] == 'queue-add':
            bridge.journal.update(job['id'], clientMessageId=params['state'][job['threadId']][-1]['id'])
        elif data['action'] == 'queue-resume' and state.get('queueBackend') == 'app-server':
            row = next(row for row in state['nativeQueue'] if row['id'] == data['messageId'])
            bridge.journal.update(job['id'], clientMessageId=row['clientUserMessageId'])
        native_response = getattr(ipc, 'protocol', None) == 'codex-app-server' and data['action'] in REQUEST_METHODS
        if native_response:
            bridge.journal.update(job['id'], nativeResponse={'session': ipc.session_id, 'requestId': params['requestId']})
        if job.get("files"):
            from carryon.sessions.file_references import guard, delivery_session
            def authorized():
                with bridge.lock:
                    bridge.check_generation(ipc, generation)
                    bridge.assert_target(job['threadId'])
                    if authorize: authorize()
            with delivery_session(bridge, job['threadId'], ipc, authorized, starts_turn=data['action'] == 'queue-add') as (runtime, owner_guard):
                response = runtime.request(method, params, version, owner,
                    guard(runtime, job['threadId'], job['files'], lambda write: guarded(lambda: owner_guard(write))))
        else:
            response = ipc.request(method, params, version, owner, guarded)
        result = response['result']
        if data['action'] == 'settings':
            if not isinstance(result, dict) or type(result.get('applied')) is not bool:
                raise IPCError('原生设置回执缺少 applied，结果待核对', uncertain=True)
            if not result['applied']:
                raise IPCError('原生未应用设置，请刷新后核对')
        bridge.journal.update(job['id'], state='completed', result=result,
                              evidence=response.get('evidence', 'native-handler-response'))
        if native_response:
            ipc.forget_response(job['threadId'], params['requestId'])
    except Exception as exc:
        uncertain = sent and (not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))


def dispatch_native_edit(bridge, ipc, generation, job, data, authorize):
    """Native edits need one durable receipt and a fresh guard for each phase."""
    tid = job['threadId']
    if job.get('sideParentId'): return False
    def authorized():
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            bridge.assert_target(tid)
            if authorize: authorize()
    if getattr(ipc, 'protocol', None) == 'codex-app-server':
        session = nullcontext((ipc, lambda write: write()))
    elif hasattr(bridge, 'native_session'):
        session = bridge.native_session(tid, authorized)
    else:
        return False
    phase, attempted, reverted = 'preparing', False, False
    try:
        with session as target:
            if target is None: return False
            runtime, owner_guard = target
            authorized()
            _, state = runtime.snapshot(tid)
            build('edit', data, state)
            client_id = str(uuid.uuid4())
            bridge.journal.update(job['id'], nativeEdit=True, originalTurnId=data['turnId'], clientMessageId=client_id)
            def before_write(stage, write):
                nonlocal phase, attempted
                with bridge.lock:
                    authorized()
                    def commit():
                        nonlocal phase, attempted
                        phase, attempted = stage, True
                        bridge.journal.update(job['id'], state='dispatching', editPhase=stage)
                        write()
                    owner_guard(commit)
            def progress(stage, evidence):
                nonlocal phase, attempted, reverted
                phase, attempted, reverted = stage, False, True
                bridge.journal.update(job['id'], editPhase=stage, **evidence)
            from carryon.app_server.editing import edit_last
            result = edit_last(runtime, tid, data['turnId'], text(data.get('prompt')), client_id, before_write, progress)
            bridge.journal.update(job['id'], state='completed', editPhase='completed', result=result,
                turnId=result['turn']['id'], evidence='native-revert-and-start')
            return True
    except Exception as exc:
        uncertain = attempted and (not isinstance(exc, IPCError) or exc.uncertain)
        message = str(exc)
        if reverted: message = ('上一轮已回退；新消息发送结果待核对：' if uncertain else '上一轮已回退，新消息未发送：') + message
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', editPhase=phase, error=message)
        return True
