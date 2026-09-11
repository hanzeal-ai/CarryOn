"""Standard-library external API example. Does not retry mutations."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description='ConnectNow 外部调用示例')
    parser.add_argument('--base', default='http://127.0.0.1:8769')
    parser.add_argument('--token-file', type=Path,
        default=Path(__file__).resolve().parents[1] / '.runtime/token')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'enable', 'disable'):
        commands.add_parser(name)
    commands.add_parser('threads').add_argument('--search', default='')
    for name in ('controller', 'history', 'job'):
        commands.add_parser(name).add_argument('id')
    for name in ('create', 'send'):
        command = commands.add_parser(name)
        if name == 'send':
            command.add_argument('id')
        command.add_argument('prompt')
        command.add_argument('--request-id', required=True,
            help='调用前保存；网络失败重试时沿用同一个 ID')
    args = parser.parse_args()
    token = os.environ.get('CONNECTNOW_TOKEN') or args.token_file.read_text().strip()
    body = None
    if args.command == 'status':
        path = '/status'
    elif args.command in ('enable', 'disable'):
        path, body = '/bridge', {'enabled': args.command == 'enable'}
    elif args.command == 'threads':
        path = '/threads?search=' + quote(args.search, safe='')
    elif args.command == 'controller':
        path, body = '/controller', {'threadId': args.id}
    elif args.command == 'history':
        path = '/threads/' + quote(args.id, safe='') + '/history'
    elif args.command == 'job':
        path = '/jobs/' + quote(args.id, safe='')
    else:
        path = '/threads' if args.command == 'create' else '/threads/' + quote(args.id, safe='') + '/messages'
        body = {'requestId': args.request_id, 'prompt': args.prompt}
    request = Request(args.base.rstrip('/') + '/api' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=30) as response:
            print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
    except HTTPError as exc:
        print(f'HTTP {exc.code}: {exc.read().decode()}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
