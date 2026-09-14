"""Native queue projection and transformations; Codex remains the queue owner."""
import copy
import time
import uuid

from .contracts import digest, text


def message(prompt, state, images=None):
    return {'id': str(uuid.uuid4()), 'text': prompt, 'cwd': state.get('cwd'),
            'createdAt': int(time.time() * 1000), 'context': {
                'prompt': prompt, 'commentAttachments': [], 'imageAttachments': [{'id': str(uuid.uuid4()), 'src': url} for url in (images or [])],
                'fileAttachments': [], 'pastedTextAttachments': [], 'addedFiles': [],
                'workspaceRoots': [state['cwd']] if state.get('cwd') else []}}


def projection(messages, source):
    if not isinstance(messages, list) or any(not isinstance(m, dict) or not isinstance(m.get('id'), str) for m in messages):
        raise ValueError('原生队列格式无法识别')
    if len({m['id'] for m in messages}) != len(messages):
        raise ValueError('原生队列存在重复消息 ID')
    return {'messages': copy.deepcopy(messages), 'fingerprint': digest(messages), 'source': source}


def transform(action, data, state, original):
    if data.get('queueFingerprint') != digest(original):
        raise ValueError('排队消息已变化，请读取最新队列后再操作')
    messages = copy.deepcopy(original)
    if action == 'queue-add':
        from .images import validate_images
        images = validate_images(data.get('images'))
        prompt = data.get('prompt')
        prompt = '' if images and isinstance(prompt, str) and len(prompt) <= 16000 and not prompt.strip() else text(prompt)
        messages.append(message(prompt, state, images))
    elif action == 'clear-queue':
        if data.get('confirmed') is not True:
            raise ValueError('请确认清空排队消息')
        messages = []
    elif action == 'queue-reorder':
        ids = data.get('messageIds')
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(messages) or set(ids) != {m['id'] for m in messages}:
            raise ValueError('messageIds 必须包含当前队列的每个消息 ID 且仅一次')
        by_id = {m['id']: m for m in messages}
        messages = [by_id[i] for i in ids]
    else:
        item = next((m for m in messages if m['id'] == data.get('messageId')), None)
        if item is None:
            raise ValueError('排队消息已不存在')
        if action == 'queue-edit':
            prompt = text(data.get('prompt'))
            item['text'] = prompt
            item['context']['prompt'] = prompt
        elif action == 'queue-delete':
            messages.remove(item)
        elif action == 'queue-resume':
            item.pop('pausedReason', None)
        else:
            raise ValueError('未知队列操作')
    # Native coordinator refuses untrusted app input; do not strip its markers.
    for item in messages:
        context = item.get('context')
        if not isinstance(context, dict):
            raise ValueError('原生排队消息缺少 context')
        if context.get('untrustedAppMessage') is not None or any(a.get('untrusted') is True for a in context.get('mcpAppModelContextAttachments') or []):
            raise ValueError('队列含需在 Codex App 确认的应用输入，请先在 App 处理')
    return messages
