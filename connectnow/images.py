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
