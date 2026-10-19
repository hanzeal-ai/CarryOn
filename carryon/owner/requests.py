"""Validate follower requests against the owned runtime before forwarding."""
from carryon.contracts import digest
from carryon.errors import IPCError
from carryon.sessions.operations import build, REQUEST_METHODS

APPROVALS = {
    'thread-follower-command-approval-decision': 'command-approval',
    'thread-follower-file-approval-decision': 'file-approval',
    'thread-follower-permissions-request-approval-response': 'permissions-approval',
    'thread-follower-submit-user-input': 'user-input',
    'thread-follower-submit-mcp-server-elicitation-response': 'mcp-response',
}
VERSIONS = {'thread-owner-discovery': 1, 'thread-follower-load-complete-history': 1,
            'thread-follower-start-turn': 2, 'thread-follower-steer-turn': 1,
            'thread-follower-interrupt-turn': 4, 'thread-follower-compact-thread': 1,
            'thread-follower-update-thread-settings': 2,
            'thread-follower-set-queued-follow-ups-state': 1,
            **{name: 1 for name in APPROVALS}}


def input_items(value):
    if not isinstance(value, list) or len(value) > 100:
        raise IPCError('invalid-input')
    for item in value:
        if not isinstance(item, dict): raise IPCError('invalid-input')
        if item.get('type') == 'text':
            if set(item) - {'type', 'text', 'text_elements'} or not isinstance(item.get('text'), str) or len(item['text']) > 16000:
                raise IPCError('unsupported-text-input')
        elif item.get('type') == 'image':
            if set(item) - {'type', 'url'} or not isinstance(item.get('url'), str):
                raise IPCError('unsupported-image-input')
        elif item.get('type') == 'skill':
            from carryon.sessions.skills import selections
            selections([{k: v for k, v in item.items() if k != 'type'}])
        elif item.get('type') == 'mention':
            from carryon.sessions.mentions import selections
            selections([{k: v for k, v in item.items() if k != 'type'}])
        else: raise IPCError('unsupported-input-type')
    return value


def forward(runtime, tid, method, params):
    state = runtime.current(tid)
    if state is None: raise IPCError('owned-runtime-not-loaded')
    active = next((t for t in reversed(state['turns']) if t['status'] == 'inProgress'), None)
    if method == 'thread-follower-start-turn':
        start = params.get('turnStart') or {}
        if not isinstance(start, dict): raise IPCError('invalid-turn-start')
        request = start.get('request') or {}
        context = start.get('context') or {}
        if not isinstance(request, dict) or not isinstance(context, dict): raise IPCError('invalid-turn-start')
        if (request.get('threadId') != tid or set(request) - {'threadId', 'input', 'clientUserMessageId'}
                or set(context) - {'inheritThreadSettings'}):
            raise IPCError('unsupported-turn-context')
        if active or state.get('requests') or state['threadRuntimeStatus']['type'] != 'idle':
            raise IPCError('thread-not-idle')
        result = runtime.start_turn(tid, {**request, 'input': input_items(request.get('input'))})
        return {'result': result}
    if method in ('thread-follower-steer-turn', 'thread-follower-interrupt-turn'):
        if active is None: raise IPCError('turn-changed')
        expected = params.get('expectedTurnId', active['turnId']) if method.endswith('steer-turn') else params.get('expectedTurnId')
        if expected != active['turnId']: raise IPCError('turn-changed')
        if method.endswith('steer-turn'):
            from carryon.sessions.skills import guard_inputs
            values = input_items(params.get('input'))
            return runtime.rpc('turn/steer', {'threadId': tid, 'expectedTurnId': expected,
                                            'input': values}, guard_inputs(runtime, tid, values))
        return runtime.rpc('turn/interrupt', {'threadId': tid, 'turnId': expected})
    if method == 'thread-follower-compact-thread':
        if active or state.get('requests'): raise IPCError('thread-not-idle')
        return runtime.rpc('thread/compact/start', {'threadId': tid})
    if method == 'thread-follower-update-thread-settings':
        if state['threadRuntimeStatus']['type'] not in ('active', 'idle'):
            raise IPCError('thread-state-unknown')
        return runtime.request(method, params)['result']
    if method == 'thread-follower-set-queued-follow-ups-state':
        if set(params.get('state', {})) != {tid}: raise IPCError('queue-thread-mismatch')
        return runtime.request(method, params)['result']
    action = APPROVALS.get(method)
    if action:
        request = next((r for r in state.get('requests', []) if type(r['id']) is type(params.get('requestId'))
                        and r['id'] == params.get('requestId') and r['method'] == REQUEST_METHODS[action]), None)
        if request is None: raise IPCError('request-no-longer-pending')
        data = {'nativeRequestId': request['id'], 'requestFingerprint': digest(request)}
        if action in ('command-approval', 'file-approval'): data['decision'] = params.get('decision')
        elif action == 'user-input':
            answers = (params.get('response') or {}).get('answers')
            if not isinstance(answers, dict) or any(not isinstance(v, dict) for v in answers.values()):
                raise IPCError('invalid-user-input-response')
            data['answers'] = {key: value.get('answers') for key, value in answers.items()}
        else: data['response'] = params.get('response')
        _, _, validated = build(action, data, state)
        result = runtime.respond(tid, validated, None, 15000)
        return result.get('result', {})
    raise IPCError('unsupported-owner-request')
