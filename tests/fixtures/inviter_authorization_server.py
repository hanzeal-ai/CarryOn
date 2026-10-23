"""Isolated HTTP console for the remote inviter browser acceptance test."""
import json
import sys
import tempfile
import threading

from carryon.cloud.console import ConsoleServer
from carryon.cloud.console_auth import password_record
from carryon.paths import save_json

with tempfile.TemporaryDirectory(prefix='carryon-inviter-browser-') as directory:
    config = {'publicUrl': 'http://127.0.0.1', 'devices': {},
              'account': password_record('test-owner', 'fixture-password-123')}
    server = ConsoleServer(('127.0.0.1', 0), config, directory)
    server.origin = server.public_url = f'http://127.0.0.1:{server.server_port}'
    server.auth.users['member'] = password_record('member', 'member-password-123')
    save_json(server.auth.users_path, server.auth.users)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({'url': server.public_url}), flush=True)
    try:
        sys.stdin.readline()
    finally:
        server.shutdown(); server.server_close(); thread.join(3)
