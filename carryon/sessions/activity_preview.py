"""Bounded, read-only notification text derived from native events."""
from carryon.sessions.timeline import completion_time


def preview(turn, kind, *, requests=(), questions=()):
    items = turn.get('items', [])
    selected = None
    text = ''
    if kind in ('approval', 'question'):
        titles = [q.get('title', '') for q in questions]
        for request in requests:
            params = request.get('params', {})
            titles.extend(q.get('question') or q.get('header', '') for q in params.get('questions', []))
            titles.append(params.get('reason') or params.get('message') or params.get('command') or '')
        text = '\n'.join(t for t in titles if isinstance(t, str) and t)
    elif kind == 'failed':
        error = turn.get('error')
        selected = next((i for i in reversed(items) if i.get('type') == 'error'), None)
        if not error and selected:
            error = selected.get('error') or selected.get('message') or selected.get('text')
        text = error.get('message', '') if isinstance(error, dict) else error
    elif turn.get('status') in ('completed', 'interrupted'):
        selected = next((i for i in reversed(items) if i.get('type') == 'agentMessage'
                         and i.get('phase') not in ('analysis', 'commentary') and i.get('delivery') != 'async'), None)
        text = selected.get('text', '') if selected else ''
    text = text if isinstance(text, str) else ''
    result = {'kind': kind, 'text': text[:6000], 'truncated': len(text) > 6000}
    if turn.get('turnId'): result['turnId'] = turn['turnId']
    if selected and selected.get('id'): result['itemId'] = selected['id']
    completed = completion_time(turn)
    if completed is not None: result['completedAt'] = completed
    return result
