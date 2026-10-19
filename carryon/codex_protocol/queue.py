"""Native queue adaptation. The app-server owns stored submissions and their IDs."""
from copy import deepcopy
from carryon.errors import IPCError


def messages(runtime, tid):
    rows, cursor, seen = [], None, set()
    while True:
        page = runtime.rpc('thread/queue/list', {'threadId': tid, 'cursor': cursor, 'limit': 100})
        rows.extend(page['data'])
        cursor = page.get('nextCursor')
        if not cursor: break
        if cursor in seen or len(rows) > 10000: raise IPCError('原生队列分页异常')
        seen.add(cursor)
    result = []
    for row in rows:
        inputs = row['input']
        result.append({'id': row['id'], 'clientUserMessageId': row['clientUserMessageId'],
            'text': '\n'.join(v['text'] for v in inputs if v['type'] == 'text'),
            'nativeInput': deepcopy(inputs), 'context': {
                'prompt': '\n'.join(v['text'] for v in inputs if v['type'] == 'text'),
                'imageAttachments': [{'id': str(i), 'src': v['url']} for i, v in enumerate(inputs)
                                     if v['type'] == 'image' and 'url' in v]}})
    return result


def replace(runtime, tid, desired, expected, before_send=None):
    """Translate exactly one desktop queue mutation to one native queue RPC."""
    current = runtime.queue_snapshot(tid, refresh=True)
    from carryon.contracts import digest
    if expected != digest(current): raise IPCError('队列已变化，请刷新后重试')
    old = {v['id']: v for v in current}
    new = {v['id']: v for v in desired}
    if len(new) != len(desired): raise IPCError('队列消息 ID 重复')
    added, removed = set(new) - set(old), set(old) - set(new)
    changed = [key for key in old.keys() & new.keys() if old[key] != new[key]]
    params = {'threadId': tid}
    if len(added) == 1 and not removed and not changed:
        item = new[next(iter(added))]
        if [v['id'] for v in desired[:-1]] != list(old) or desired[-1]['id'] != item['id']:
            raise IPCError('队列已变化，请刷新')
        context = item.get('context') or {}
        if set(context) - {'prompt', 'commentAttachments', 'imageAttachments', 'fileAttachments', 'pastedTextAttachments', 'addedFiles', 'workspaceRoots', 'skills', 'mentions'}:
            raise IPCError('不支持此排队消息上下文')
        if any(context.get(k) for k in ('commentAttachments', 'fileAttachments', 'pastedTextAttachments', 'addedFiles')):
            raise IPCError('排队附件类型尚不支持')
        from carryon.sessions.images import validate_images
        from carryon.contracts import text
        images = validate_images([v['src'] for v in context.get('imageAttachments', [])])
        from carryon.sessions.skills import inputs
        from carryon.sessions.mentions import inputs as mention_inputs
        skill_input = inputs(context.get('skills')) + mention_inputs(context.get('mentions'))
        prompt = text(item.get('text'), allow_empty=bool(images or skill_input))
        params.update(clientUserMessageId=item['id'], input=([{'type': 'text', 'text': prompt}] if prompt else []) +
                      [{'type': 'image', 'url': url} for url in images] + skill_input)
        method = 'add'
    elif len(removed) == 1 and not added and not changed:
        if [v['id'] for v in desired] != [v['id'] for v in current if v['id'] not in removed]:
            raise IPCError('队列已变化，请刷新')
        params['queuedSubmissionId'] = next(iter(removed)); method = 'delete'
    elif not added and not removed and len(changed) == 1 and list(new) == list(old):
        key = changed[0]; item = new[key]
        resumed = deepcopy(old[key]); resumed.pop('pausedReason', None)
        if old[key].get('pausedReason') and resumed == item:
            if not runtime.queue_idle(runtime.current(tid)): raise IPCError('会话不再空闲')
            from carryon.sessions.skills import guard_inputs
            before_send = guard_inputs(runtime, tid, old[key]['nativeInput'], before_send)
            result = runtime.rpc('thread/queue/start', {'threadId': tid, 'queuedSubmissionId': key}, before_send)
            runtime.record_started(tid, result['turn'])
            return result
        original = deepcopy(old[key]); original['text'] = item['text']; original['context']['prompt'] = item['text']
        if original != item: raise IPCError('只能修改排队消息正文')
        from carryon.contracts import text
        prompt = text(item['text'])
        inputs = old[key]['nativeInput']
        if any(v['type'] == 'text' and v.get('text_elements') for v in inputs):
            raise IPCError('带引用的排队消息请在原生客户端编辑')
        params.update(queuedSubmissionId=key, input=[{'type': 'text', 'text': prompt}] +
                      [v for v in inputs if v['type'] != 'text']); method = 'update'
    elif not added and not removed and not changed:
        params['queuedSubmissionIds'] = list(new); method = 'reorder'
    else:
        raise IPCError('队列已变化或操作包含多个变更，请刷新后逐项操作')
    from carryon.sessions.skills import guard_inputs
    before_send = guard_inputs(runtime, tid, params.get('input', []), before_send)
    result = runtime.rpc('thread/queue/' + method, params, before_send)
    return result
