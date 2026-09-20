"""Packaged product defaults; per-install overrides stay in advanced settings."""
import json
from pathlib import Path
from urllib.parse import urlsplit


def configuration():
    value = json.loads(Path(__file__).with_name('product.json').read_text())
    url = value['cloudURL']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('产品云端地址必须是完整 HTTPS 地址')
    return {**value, 'cloudURL': url.rstrip('/')}


def cloud_url():
    return configuration()['cloudURL']
