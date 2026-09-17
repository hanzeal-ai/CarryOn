#!/usr/bin/env python3
"""Generate the public app update manifest; never upload or publish it."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'hanzeal-ai/CarryOn'


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,9}){0,2}', value):
        raise ValueError('Invalid release version')
    return value


def ios_releases(path):
    entries = json.loads(Path(path).read_text())
    if not isinstance(entries, list) or len(entries) > 2:
        raise ValueError('iOS releases must be an array with at most one entry per Apple channel')
    seen = set()
    required = {'platform', 'channel', 'bundleIdentifier', 'version', 'build', 'minimumSystemVersion', 'url', 'notes'}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required or entry['platform'] != 'ios':
            raise ValueError('Invalid iOS release fields')
        if entry['bundleIdentifier'] != 'com.hanzeal.carryon':
            raise ValueError('Unexpected iOS bundle identifier')
        for key in ('version', 'build', 'minimumSystemVersion'):
            version(entry[key])
        channel = entry['channel']
        if channel not in ('testflight', 'app-store') or channel in seen:
            raise ValueError('Unsupported or duplicate iOS channel')
        seen.add(channel)
        if not isinstance(entry['notes'], str) or len(entry['notes']) > 8000 or not isinstance(entry['url'], str):
            raise ValueError('Invalid iOS release notes or URL')
        url = urlsplit(entry['url'])
        if url.scheme != 'https' or url.username or url.password or url.port or url.query or url.fragment:
            raise ValueError('Apple update links must be credential-free HTTPS URLs')
        if channel == 'testflight':
            valid = url.hostname == 'testflight.apple.com' and re.fullmatch(r'/join/[A-Za-z0-9]{8}/?', url.path)
        else:
            valid = url.hostname == 'apps.apple.com' and re.fullmatch(r'/(?:[a-z]{2}/)?app/(?:[^/]+/)?id[0-9]+/?', url.path)
        if not valid:
            raise ValueError('Invalid Apple update link')
    return entries


def manifest(archives, ios_path, notes=''):
    releases = ios_releases(ios_path)
    if not isinstance(notes, str) or len(notes) > 8000:
        raise ValueError('Release notes are too long')
    seen = set()
    for archive in map(Path, archives):
        match = re.fullmatch(r'CarryOn-([0-9]+\.[0-9]+\.[0-9]+)-macos-(arm64|x86_64)\.dmg', archive.name)
        if not match or not archive.is_file() or archive.stat().st_size == 0:
            raise ValueError('Expected an existing, non-empty versioned Mac DMG')
        release, arch = match.groups(); version(release)
        if arch in seen:
            raise ValueError('Duplicate Mac architecture')
        seen.add(arch)
        releases.append({'platform': 'macos', 'channel': 'dmg', 'architecture': arch,
                         'bundleIdentifier': 'local.carryon.desktop', 'version': release, 'build': release,
                         'minimumSystemVersion': '13.0',
                         'url': f'https://github.com/{REPOSITORY}/releases/download/v{release}/{archive.name}',
                         'notes': notes})
    return {'schemaVersion': 1, 'releases': releases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mac-dmg', action='append', default=[], type=Path)
    parser.add_argument('--ios-releases', type=Path, default=ROOT/'release/ios-updates.json')
    parser.add_argument('--notes-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = manifest(args.mac_dmg, args.ios_releases, args.notes_file.read_text() if args.notes_file else '')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(args.output)
    print(f'Generated {args.output} with {len(result["releases"])} release entries; not published')


if __name__ == '__main__':
    main()
