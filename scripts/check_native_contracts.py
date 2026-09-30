#!/usr/bin/env python3
"""Read-only check of CarryOn's pinned desktop IPC versions against an installed app."""
import argparse
import json
from pathlib import Path
import plistlib
import re
import struct
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def installed_contract(app):
    resources = app / 'Contents/Resources'
    with (app / 'Contents/Info.plist').open('rb') as stream:
        version = plistlib.load(stream)['CFBundleShortVersionString']
    with (resources / 'app.asar').open('rb') as stream:
        prefix = stream.read(16)
        if len(prefix) != 16:
            raise ValueError('Invalid ASAR header')
        _, header_size, _, json_size = struct.unpack('<4I', prefix)
        if not 0 < json_size <= 32 * 1024 * 1024:
            raise ValueError('Invalid ASAR index size')
        header = json.loads(stream.read(json_size))
        candidates = []
        # This is the raw shared transport version table, not the renderer's
        # inferred capability list. A layout change must fail visibly.
        assets = header['files']['.vite']['files']['build']['files']
        for name, entry in assets.items():
            if not name.endswith('.js') or entry.get('unpacked') or entry.get('size', 0) > 16 * 1024 * 1024:
                continue
            stream.seek(8 + header_size + int(entry['offset']))
            source = stream.read(entry['size']).decode('utf-8')
            for match in re.finditer(r'\{(?:"[a-z-]+":\d+,?)+\}', source):
                table = json.loads(match.group())
                if 'thread-stream-state-changed' in table and 'thread-follower-update-thread-settings' in table:
                    candidates.append(table)
        unique = {json.dumps(table, sort_keys=True) for table in candidates}
        if len(unique) != 1:
            raise ValueError('Native transport version table is missing or ambiguous')
        return {'appVersion': version, 'versions': json.loads(unique.pop())}


def implemented_versions():
    from carryon.desktop_ipc.ipc import DesktopIPC
    from carryon.desktop_ipc.events import VERSIONS
    from carryon.sessions.operations import METHODS
    return {**VERSIONS, **{'thread-follower-' + name: version for name, version in METHODS.values()},
        'thread-stream-state-changed': DesktopIPC.STREAM_VERSION,
        'thread-stream-following-changed': DesktopIPC.FOLLOW_VERSION,
        'thread-owner-discovery': DesktopIPC.OWNER_VERSION,
        'thread-follower-load-complete-history': DesktopIPC.HISTORY_VERSION,
        'thread-follower-start-turn': DesktopIPC.START_VERSION}


def compare(expected, actual):
    differences = []
    for name, version in expected.items():
        if actual.get(name) != version:
            differences.append(f'{name}: expected {version}, got {actual.get(name)!r}')
    if differences:
        raise ValueError('\n'.join(differences))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=Path('/Applications/ChatGPT.app'))
    args = parser.parse_args()
    native = installed_contract(args.app)
    compare(implemented_versions(), native['versions'])
    print('Desktop IPC versions verified against installed App ' + native['appVersion'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
