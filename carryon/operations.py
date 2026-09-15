"""Bounded adapters for the desktop follower protocol (26.901.51231)."""
import re
import time
import uuid

from .ipc import IPCError
from .contracts import digest, text
from .contracts import settings as validate_settings, approval, approval_choices, validate, SCHEMAS
from .queue import transform, message as queued_message
from .thread_status import project_status

METHODS = {
    'interrupt': ('interrupt-turn', 4), 'steer': ('steer-turn', 1),
    'compact': ('compact-thread', 1), 'settings': ('update-thread-settings', 1),
    'edit': ('edit-last-user-turn', 2), 'resume': ('edit-last-user-turn', 2), 'clear-queue': ('set-queued-follow-ups-state', 1),
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
    last = items[-1] if items else {}
    text = next((i.get('text', '') for i in last.get('params', {}).get('input', [])
                 if i.get('type') == 'text'), '')
    requests = []
    for r in state.get('requests', []):
        if not isinstance(r, dict):
            continue
        action = next((a for a, m in REQUEST_METHODS.items() if m == r.get('method')), None)
        if action:
            requests.append({'id': r.get('id'), 'action': action, 'method': r['method'],
                             'fingerprint': digest(r), 'params': r.get('params', {}),
                             'decisions': approval_choices(action, r.get('params', {}))})
    return {'activeTurnId': active.get('turnId') if active else None,
            'lastTurnId': last.get('turnId'), 'lastTurnStatus': last.get('status'), 'lastUserText': text,
            'settings': {k: v for k, v in (state.get('latestThreadSettings') or {}).items()
                         if k in SCHEMAS['settings']['properties'] and k != 'threadId'}, 'requests': requests}


def build(action, data, state):
    if action not in METHODS:
        raise ValueError('不支持的会话操作')
    c = controls(state)
    runtime = state.get('threadRuntimeStatus', {}).get('type')
    params = {'conversationId': state['id']}
    if action in ('interrupt', 'steer'):
        if runtime != 'active' or not c['activeTurnId'] or data.get('expectedTurnId') != c['activeTurnId']:
            raise ValueError('执行轮次已改变，请刷新后操作')
        if action == 'interrupt':
            params.update(mode='user-stop', expectedTurnId=c['activeTurnId'])
        else:
            from .images import validate_images
            images = validate_images(data.get('images'))
            prompt = data.get('prompt')
            prompt = '' if images and isinstance(prompt, str) and len(prompt) <= 16000 and not prompt.strip() else text(prompt)
            params.update(input=([{'type': 'text', 'text': prompt, 'text_elements': []}] if prompt else []) + [{'type': 'image', 'url': url} for url in images],
                          clientUserMessageId=str(uuid.uuid4()), attachments=[],
                          restoreMessage=queued_message(prompt, state, images))
    elif action in QUEUE_ACTIONS:
        if runtime not in ('active', 'idle'):
            raise ValueError('会话运行状态尚未确认')
        params['state'] = {state['id']: transform(action, data, state, state['nativeQueue'])}
    elif action == 'settings':
        if runtime not in ('active', 'idle'):
            raise ValueError('会话运行状态尚未确认')
        params['threadSettings'] = validate_settings(data.get('settings'), state['id'])
    elif action in ('compact', 'edit', 'resume'):
        if project_status(state)['state'] != 'idle':
            raise ValueError('此操作需要已确认空闲且没有待处理请求的会话')
        if action in ('edit', 'resume'):
            if action == 'resume' and (c['lastTurnStatus'] != 'interrupted' or not turns(state)[-1].get('params', {}).get('input')):
                raise ValueError('只有已暂停的最后一轮可以重新启动')
            if data.get('turnId') != c['lastTurnId'] or (action == 'edit' and not c['lastUserText']):
                raise ValueError('最后一轮已改变或不支持文本编辑')
            if action == 'edit' and data.get('confirmed') is not True:
                raise ValueError('编辑会替换最后一轮并重新执行，请确认')
            params.update(turnId=c['lastTurnId'], message=c['lastUserText'] if action == 'resume' else text(data.get('prompt')),
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


def submit(bridge, thread_id, data, source=None, authorize=None, prepared=None, parent_id=None):
    from .errors import BridgeError
    from .catalog import valid_id
    valid_id(thread_id)
    bridge.assert_target(thread_id, parent_id)
    ipc, generation = bridge.require()
    action, request_id = data.get('action'), data.get('requestId')
    if action not in METHODS:
        raise ValueError('不支持的会话操作')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
        raise ValueError('requestId 必须为 8–100 位字母、数字、横线或下划线')
    fingerprint = digest([thread_id, data] + ([parent_id] if parent_id else []))
    with bridge.lock:
        bridge.check_generation(ipc, generation)
        previous = bridge.journal.get(request_id)
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise BridgeError('requestId 已用于不同内容')
            return previous
        if any(j['threadId'] == thread_id
               and (j['state'] in ('preparing', 'dispatching', 'uncertain')
                    or (action in ('compact', 'edit', 'resume') and j['state'] == 'accepted'))
               for j in bridge.journal.list()):
            raise BridgeError('此会话有正在投递或结果待确认的操作，请先核对')
        job = {'id': request_id, 'fingerprint': fingerprint, 'kind': 'operation:' + action,
               'threadId': thread_id, 'created': time.time(), 'state': 'preparing'}
        if source:job.update(source)
        if parent_id is not None: job['sideParentId'] = parent_id
        bridge.journal.insert(job)
    import threading
    threading.Thread(target=dispatch, args=(bridge, ipc, generation, job, data, authorize, prepared), daemon=True).start()
    return job


def dispatch(bridge, ipc, generation, job, data, authorize=None, prepared=None):
    sent = False
    try:
        if prepared is not None and hasattr(ipc, 'current') and ipc.current(job['threadId']) is prepared[1]:
            owner, state = prepared
        else:
            owner, state = ipc.snapshot(job['threadId'])
        bridge.assert_target(job['threadId'], job.get('sideParentId'), state)
        if data['action'] in QUEUE_ACTIONS:
            state = {**state, 'nativeQueue': bridge.queue(job['threadId'], job.get('sideParentId'))['messages']}
        method, version, params = build(data['action'], data, state)
        def guarded(write):
            nonlocal sent
            with bridge.lock:
                bridge.check_generation(ipc, generation)
                if authorize:authorize()
                bridge.assert_target(job['threadId'], job.get('sideParentId'))
                # Recheck streamed state immediately before writing, when available.
                current = ipc.current(job['threadId']) if hasattr(ipc, 'current') else None
                if prepared is not None and current is None:
                    raise IPCError('会话状态正在重新同步，此请求未投递')
                if data['action'] in QUEUE_ACTIONS:
                    current = {**(current or state), 'nativeQueue': bridge.queue(job['threadId'], job.get('sideParentId'))['messages']}
                if current is not None:
                    build(data['action'], data, current)
                bridge.journal.update(job['id'], state='dispatching')
                sent = True
                write()
        if data['action'] == 'steer':
            bridge.journal.update(job['id'], clientMessageId=params['clientUserMessageId'])
        elif data['action'] == 'queue-add':
            bridge.journal.update(job['id'], clientMessageId=params['state'][job['threadId']][-1]['id'])
        result = ipc.request(method, params, version, owner, guarded)['result']
        bridge.journal.update(job['id'], state='completed', result=result,
                              evidence='native-handler-response')
    except Exception as exc:
        uncertain = sent and (not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
