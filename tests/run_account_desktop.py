"""Exercise the native desktop account model through its real CLI and TLS server."""
import os
from pathlib import Path
import platform
import shlex
import ssl
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from carryon.account_settings import AccountSettings
from carryon.console import ConsoleServer

with tempfile.TemporaryDirectory(prefix='carryon-account-desktop-') as temp:
    root = Path(temp)
    cert, key = root/'cert.pem', root/'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                    '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
    config = {'publicUrl': 'https://localhost', 'accountSetup': True, 'devices': {}}
    token = AccountSettings(config, root/'cloud').bootstrap()
    server = ConsoleServer(('127.0.0.1', 0), config, root/'cloud')
    server.origin = server.public_url = f'https://localhost:{server.server_port}'
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    cli = root/'cli'
    cli.write_text('#!/bin/sh\ncd '+shlex.quote(str(ROOT))+'\nexec '+shlex.quote(sys.executable)+' -m carryon "$@"\n');cli.chmod(0o700)
    cli = Path(os.environ.get('CARRYON_TEST_CLI', str(cli)))
    binary = root/'account-desktop-smoke'
    try:
        subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5', '-D', 'DESKTOP_TEST',
                        '-target', platform.machine()+'-apple-macos13.0', *map(str, sorted((ROOT/'desktop').glob('*.swift'))),str(ROOT/'iOS/CarryOn/Core/AppUpdate.swift'),
                        str(ROOT/'tests/AccountDesktopSmoke.swift'), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=60, env={**os.environ,
            'CARRYON_DESKTOP_CLI':str(cli), 'CARRYON_HOME':str(root/'local'), 'SSL_CERT_FILE':str(cert),
            'CARRYON_TEST_ACCOUNT_URL':f'https://localhost:{server.server_port}', 'CARRYON_TEST_SETUP_TOKEN':token})
        server.auth.verify({'username':'new-owner','password':'new-desktop-test-password'})
    finally:
        server.shutdown();server.server_close();worker.join(3)
