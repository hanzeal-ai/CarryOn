"""Bounded inline image inputs, passed directly to the native turn contract."""
import base64
import binascii
import re

MAX_IMAGE_BYTES=200*1024
MAX_IMAGES=3
MAX_REQUEST_BYTES=900000


def validate_images(images):
    if images is None:return []
    if not isinstance(images,list) or len(images)>MAX_IMAGES:raise ValueError('每次最多发送 3 张图片')
    result=[]
    for image in images:
        if not isinstance(image,str) or len(image)>MAX_IMAGE_BYTES*4//3+128:
            raise ValueError('图片过大，请压缩后重试')
        match=re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',image)
        if not match:raise ValueError('仅支持 PNG、JPEG 和 WebP 图片')
        try:data=base64.b64decode(match[2],validate=True)
        except (ValueError,binascii.Error):raise ValueError('图片编码无效') from None
        valid=(match[1]=='png' and data.startswith(b'\x89PNG\r\n\x1a\n') or
               match[1]=='jpeg' and data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9') or
               match[1]=='webp' and data[:4]==b'RIFF' and data[8:12]==b'WEBP')
        if not valid or len(data)>MAX_IMAGE_BYTES:raise ValueError('图片内容或大小无效')
        result.append(image)
    return result


def image_id(path):
    import hashlib
    return hashlib.sha256(path.encode()).hexdigest()


def read_history_image(history, identifier):
    """Resolve only native user image attachments from the authorized history."""
    import os
    import stat
    from .errors import BridgeError
    paths = {part.get('path') for item in history.get('timeline', [])
             if item.get('type') in ('userMessage', 'steeringUserMessage')
             for part in item.get('data', {}).get('content', item.get('data', {}).get('input', []))
             if part.get('type') == 'localImage' and isinstance(part.get('path'), str)}
    path = next((p for p in paths if image_id(p) == identifier), None)
    if path is None: raise BridgeError('该会话中没有这张图片', 404)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8*1024*1024:
                raise ValueError('图片超过 8 MB 或不是普通文件')
            data = handle.read(8*1024*1024+1)
        if len(data) > 8*1024*1024: raise ValueError('图片超过 8 MB')
        mime = ('png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
                'jpeg' if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9') else
                'webp' if data[:4] == b'RIFF' and data[8:12] == b'WEBP' else
                'gif' if data[:6] in (b'GIF87a', b'GIF89a') else None)
        if mime is None: raise ValueError('暂不支持这张图片的格式')
        return {'url': 'data:image/'+mime+';base64,'+base64.b64encode(data).decode()}
    except OSError:
        raise BridgeError('原图片已移动、删除或无法读取', 404) from None
