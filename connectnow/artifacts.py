"""Attachments explicitly referenced by displayed assistant output, scoped to history."""
import base64
import mimetypes
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote
from .errors import BridgeError
from .images import image_id
from .user_messages import unwrap_user_message

LINK = re.compile(r'!?\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}


def references(kind, data):
    paths = []
    if kind in ('userMessage', 'steeringUserMessage'):
        parts = data.get('content', data.get('input', []))
        body = '\n'.join(p.get('text', '') for p in parts if p.get('type') == 'text')
        paths = unwrap_user_message(body)[1]
    if kind == 'agentMessage':
        for match in LINK.finditer(data.get('text', '')):
            path = unquote(match[1].strip('<>'))
            if path.startswith('/'):
                paths.append(re.sub(r':\d+(?::\d+)?$', '', path))
    if kind == 'imageView' and isinstance(data.get('path'), str):
        paths.append(data['path'])
    inline = []
    if kind in ('mcpToolCall', 'dynamicToolCall'):
        result = data.get('result')
        parts = result.get('content', []) if isinstance(result, dict) else data.get('contentItems', [])
        for part in parts if isinstance(parts, list) else []:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'image' and isinstance(part.get('data'), str) and part.get('mimeType') in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
                url = 'data:' + part['mimeType'] + ';base64,' + part['data']
                inline.append({'id': image_id(url), 'url': url, 'kind': 'image', 'name': '工具结果图片'})
    if kind == 'imageGeneration' and isinstance(data.get('result'), str):
        result = data['result']
        if result.startswith('/'):
            paths.append(result)
        elif result.startswith('data:image/'):
            inline.append({'id': image_id(result), 'url': result, 'kind': 'image', 'name': '生成图片'})
    return inline + [{'id': image_id(path), 'path': path, 'name': Path(path).name,
             'kind': 'image' if Path(path).suffix.lower() in IMAGE_SUFFIXES else 'file'}
            for path in dict.fromkeys(paths) if Path(path).is_absolute()]


def read_artifact(history, identifier):
    allowed = [ref for item in history.get('timeline', [])
               for ref in references(item.get('type'), item.get('data', {}))]
    ref = next((ref for ref in allowed if ref['id'] == identifier and ref.get('path')), None)
    if ref is None:
        raise BridgeError('该会话中没有此附件', 404)
    try:
        fd = os.open(ref['path'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
                raise ValueError('附件超过 8 MB 或不是普通文件')
            data = handle.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('附件超过 8 MB')
    except OSError:
        raise BridgeError('附件已移动、删除或无法读取', 404) from None
    mime = mimetypes.guess_type(ref['name'])[0] or 'application/octet-stream'
    return {**ref, 'mime': mime, 'base64': base64.b64encode(data).decode()}
