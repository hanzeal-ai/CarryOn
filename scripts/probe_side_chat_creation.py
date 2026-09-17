#!/usr/bin/env python3
"""Check whether this running desktop exposes an entry for the side-chat experiment.

Run from the target Codex conversation:
    python3 scripts/probe_side_chat_creation.py

This is an entry-point probe, not a working side-chat creator. It deliberately
does not invent a global openSideChat API, restart the desktop, patch its bundle,
or substitute a message to the parent. Exit 2 means the experiment is blocked.
"""
import argparse
import json
import os
import plistlib
import struct
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def native_entry(resources):
    """Inspect the installed bundle without loading or modifying application code."""
    with (resources / 'app.asar').open('rb') as stream:
        prefix = stream.read(16)
        if len(prefix) != 16:
            raise ValueError('Invalid ASAR header')
        _, header_size, _, json_size = struct.unpack('<4I', prefix)
        if not 0 < json_size < 32 * 1024 * 1024:
            raise ValueError('Invalid ASAR header size')
        header = json.loads(stream.read(json_size))
        assets = header['files']['webview']['files']['assets']['files']
        matches = [name for name in assets if name.startswith('thread-pin-shortcut-bridge-') and name.endswith('.js')]
        if len(matches) != 1:
            return {'found': False, 'reason': 'Native module layout differs from inspected build'}
        name = matches[0]
        item = assets[name]
        stream.seek(8 + header_size + int(item['offset']))
        source = stream.read(item['size']).decode('utf-8')
        return {'found': all(marker in source for marker in ('sourceConversationId', 'ephemeral:!0', 'sideConversation:!0', 'prepareConversation')),
                'module': 'webview/assets/' + name,
                'requires': ['live renderer scope', 'native conversation manager', 'parent identity verification']}


def discover(endpoint, timeout):
    address = urlsplit(endpoint)
    if address.scheme != 'http' or address.hostname not in ('127.0.0.1', 'localhost', '::1') or address.username or address.password or address.query or address.fragment or address.path not in ('', '/'):
        raise ValueError('CDP endpoint must be a loopback HTTP origin')
    # Do not send local debugging probes through the user's configured proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(endpoint.rstrip('/') + path, timeout=timeout) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError('CDP discovery response is too large')
            return json.loads(body)
    version, targets = get('/json/version'), get('/json/list')
    if not isinstance(version, dict) or not isinstance(targets, list):
        raise ValueError('Invalid CDP discovery response')
    # Never choose an arbitrary page or return unrelated page titles/URLs.
    return {'browser': version.get('Browser'),
            'pageTargetCount': sum(isinstance(t, dict) and t.get('type') == 'page' for t in targets)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-id', default=os.environ.get('CODEX_THREAD_ID'))
    parser.add_argument('--endpoint', default='http://127.0.0.1:9222')
    parser.add_argument('--app', type=Path, default=Path('/Applications/ChatGPT.app'))
    parser.add_argument('--timeout', type=float, default=2)
    args = parser.parse_args()
    try:
        if not args.parent_id or str(uuid.UUID(args.parent_id)) != args.parent_id:
            raise ValueError('Pass --parent-id or run within the target Codex conversation')
        if not 0 < args.timeout <= 10:
            raise ValueError('timeout must be between 0 and 10 seconds')
        result = {'parentId': args.parent_id, 'requestedText': 'hello',
                  'created': False, 'sent': False, 'status': 'blocked'}
        resources = args.app / 'Contents' / 'Resources'
        with (args.app / 'Contents' / 'Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        result['desktopVersion'] = info.get('CFBundleShortVersionString')
        result['nativeEntry'] = native_entry(resources)
        result['stage'] = 'cdp-discovery'
        try:
            result['cdp'] = discover(args.endpoint, args.timeout)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            result['reason'] = 'No usable CDP endpoint: ' + str(exc)
        else:
            result['stage'] = 'native-runtime-binding'
            result['reason'] = ('CDP is reachable, but the native scope/manager binding has not been verified. '
                                'Do not invoke a guessed function or choose an arbitrary conversation.')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'blocked', 'created': False, 'sent': False, 'reason': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
