"""Real iOS app model → HTTPS/WSS console → connector → CLI daemon/TUI.

Uses an isolated CODEX_HOME and deterministic local Responses model; never a
personal account or production endpoint. Requires macOS, Xcode and Codex 0.155.1.
"""
import argparse
from contextlib import suppress
from http.server import ThreadingHTTPServer
import json
import hashlib
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_cli_protocol_probe import Fixture, Terminal, wait
from carryon.codex_cli.bridge import CliBridge
from carryon.cloud.console import ConsoleServer, ConsoleHandler
from carryon.cloud.console_auth import password_record
from carryon.cloud.cloud import CloudConnector
from carryon.store import Journal
from carryon.workspaces.workspace_access import CAPABILITIES
from carryon.lifecycle import BridgeLifecycle
from carryon.workspaces.workspace import Workspace

BUNDLE = 'com.hanzeal.carryon.cliintegration'


def build(repo, output, device):
    source = output / 'source'; source.mkdir(parents=True, exist_ok=True)
    for name in ('CarryOn', 'CarryOn.xcodeproj', 'Tests'):
        shutil.copytree(repo / 'iOS' / name, source / name, dirs_exist_ok=True)
    shutil.copy2(repo / 'iOS/Package.swift', source / 'Package.swift')
    shutil.copy2(repo / 'tests/fixtures/ios_cli_integration.swift', source / 'CarryOn/App/CarryOnApp.swift')
    project = source / 'CarryOn.xcodeproj/project.pbxproj'
    project.write_text(project.read_text().replace('com.hanzeal.carryon', BUNDLE))
    (output / 'carryon').mkdir(exist_ok=True)
    shutil.copy2(repo / 'carryon/product.json', output / 'carryon/product.json')
    with (output / 'build.log').open('w') as log:
        subprocess.run(['xcodebuild', '-project', str(source / 'CarryOn.xcodeproj'), '-scheme', 'CarryOn',
            '-configuration', 'Debug', '-sdk', 'iphonesimulator', '-destination', 'id=' + device,
            '-derivedDataPath', str(output / 'build'), '-clonedSourcePackagesDirPath', str(repo / 'iOS/.build/SourcePackages'),
            '-disableAutomaticPackageResolution', '-skipPackageUpdates', 'ARCHS=arm64', 'CODE_SIGN_IDENTITY=-', 'build'], stdout=log, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--shared-binding', action='store_true', help='Join CLI through an existing desktop binding without a second phone scan')
    parser.add_argument('--workspace-connections', action='store_true', help='Add a desktop protocol fixture to test connection isolation')
    parser.add_argument('--codex', default=shutil.which('codex'))
    args = parser.parse_args()
    if args.shared_binding: args.workspace_connections = True
    repo = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    if not args.skip_build: build(repo, output, args.simulator)
    if args.skip_build and (output / 'source/CarryOn/App/CarryOnApp.swift').read_bytes() != (repo / 'tests/fixtures/ios_cli_integration.swift').read_bytes():
        raise ValueError('Cached iOS build source differs from current fixture; rebuild required')
    app = output / 'build/Build/Products/Debug-iphonesimulator/CarryOn.app'
    subprocess.run(['xcrun', 'simctl', 'install', args.simulator, str(app)], check=True)
    container = Path(subprocess.check_output(['xcrun', 'simctl', 'get_app_container', args.simulator, BUNDLE, 'data'], text=True).strip())
    report = {'passed': False, 'checks': [], 'codexVersion': subprocess.check_output([args.codex, '--version'], text=True).strip(),
        'limitations': ['Deterministic local model, no real model inference', 'iPhone simulator; physical phone and public Internet not exercised']}
    report['sourceHashes'] = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [*sorted((repo / 'carryon').rglob('*.py')), repo / 'tests/run_cli_mobile_integration.py',
                     repo / 'tests/run_cli_protocol_probe.py', repo / 'tests/fixtures/ios_cli_integration.swift']}
    terminal = bridge = connector = console = model = lifecycle = None
    desktop_bridge = desktop_connector = None
    old_registry = os.environ.get("CARRYON_REGISTRY_DIR")
    env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_THREAD_ID', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE')}
    with tempfile.TemporaryDirectory(prefix='co-', dir='/tmp') as temp:
        root = Path(temp).resolve(); home = root / 'home'; home.mkdir(); work = root / 'work'; work.mkdir()
        env.update(CODEX_HOME=str(home), TERM='xterm-256color', NO_COLOR='1')
        # Native daemon expects its managed binary location; this link belongs only to the fixture home.
        managed = home / 'packages/standalone/current'; managed.mkdir(parents=True)
        (managed / 'codex').symlink_to(args.codex)
        fixture = Fixture(work, output)
        model = ThreadingHTTPServer(('127.0.0.1', 0), fixture.handler()); model.daemon_threads = True
        threading.Thread(target=model.serve_forever, daemon=True).start()
        (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\napproval_policy="on-request"\nsandbox_mode="workspace-write"\n'
            f'[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:{model.server_port}/v1"\nwire_api="responses"\nrequires_openai_auth=false\n[projects."{work}"]\ntrust_level="trusted"\n')
        def daemon(action):
            return subprocess.run([args.codex, 'app-server', 'daemon', action], env=env, cwd=work, capture_output=True, text=True, timeout=20, check=True)
        def check(name):
            report['checks'].append(name); print('PASS', name, flush=True)
        def start(tag):
            return bridge.ipc.rpc('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text': tag, 'text_elements': []}]})['turn']['id']
        def text():
            return json.dumps(bridge.ipc.current(tid) or {})
        def completed(tag):
            return any(t['status'] == 'completed' and tag + '_ALPHA_' in json.dumps(t)
                for t in bridge.ipc.read_turns(tid))
        def step(name):
            nonlocal terminal
            if name == 'cli-stream': terminal.send('CLI_STREAM')
            elif name == 'release-cli-stream': fixture.gate('CLI_STREAM').set()
            elif name == 'verify-phone-stream':
                wait(lambda: 'CARRYON_STREAM_ALPHA_' in terminal.text(), 'phone delta in actual TUI')
                assert not completed('CARRYON_STREAM')
                fixture.gate('CARRYON_STREAM').set()
            elif name == 'cli-approval': terminal.send('APPROVAL_CARRYON')
            elif name == 'verify-phone-approval':
                assert (work / 'approval_carryon.txt').read_text() == 'approved\n'
                assert not bridge.ipc.current(tid)['requests']
            elif name == 'approve-in-cli':
                wait(lambda: 'approval_cli.txt' in terminal.text() and 'Press enter to confirm' in terminal.text().split('approval_cli.txt')[-1], 'CLI approval choices')
                terminal.send('')
            elif name == 'native-disconnect':
                previous = bridge.ipc.session_id
                bridge.ipc.connection.handler.connection.shutdown(socket.SHUT_RDWR)
                fixture.gate('DISCONNECT_CARRYON').set()
                wait(lambda: bridge.status()['enabled'] and bridge.ipc.session_id != previous, 'automatic attachment reconnect')
                wait(lambda: completed('DISCONNECT_CARRYON'), 'native task survived attachment close')
            elif name == 'pending-reconnect':
                before = bridge.ipc.current(tid)['requests'][0]['id']
                previous = bridge.ipc.session_id
                bridge.ipc.connection.handler.connection.shutdown(socket.SHUT_RDWR)
                wait(lambda: bridge.status()['enabled'] and bridge.ipc.session_id != previous, 'automatic approval reconnect')
                wait(lambda: bridge.ipc.current(tid)['requests'], 'native pending request replay')
                assert bridge.ipc.current(tid)['requests'][0]['id'] == before
            elif name == 'cli-disconnect':
                terminal.send('DISCONNECT_CLI')
                wait(lambda: 'DISCONNECT_CLI_ALPHA_' in text(), 'CLI started task')
                terminal.close(); terminal = None
                fixture.gate('DISCONNECT_CLI').set()
                wait(lambda: completed('DISCONNECT_CLI'), 'task survived CLI exit')
            elif name == 'phone-disconnect':
                start('RECONNECT'); wait(lambda: completed('RECONNECT'), 'task while phone disconnected')
            elif name == 'verify-final':
                for tag in ('approval_carryon', 'approval_cli', 'late_approval'):
                    assert (work / (tag + '.txt')).read_text() == 'approved\n'
                assert len([c for c in fixture.calls if c['tag'] == 'LATE_APPROVAL' and not c['toolDone'] and c['toolNames']]) == 1
            else: raise ValueError(name)
            check(name)
        class Handler(ConsoleHandler):
            def handle_api(self, method):
                if self.path.startswith('/console/fixture/'):
                    if not self.session_key(): return self.reply(401, {'error': 'Login required'})
                    self.body()
                    try: step(self.path.rsplit('/', 1)[-1]); self.reply(200, {'ok': True})
                    except Exception as exc: self.reply(500, {'error': repr(exc)})
                else: super().handle_api(method)
        old_ca = os.environ.get('SSL_CERT_FILE')
        try:
            report['daemon'] = json.loads(daemon('start').stdout)
            bridge = CliBridge(home, Journal(root / 'jobs.sqlite'))
            factory = bridge.ipc_factory
            wire_lock = threading.Lock()
            def traced_client(*args, **kwargs):
                client = factory(*args, **kwargs)
                receive = client.receive
                def traced_receive(value):
                    with wire_lock, (output / 'native-wire.jsonl').open('a') as wire:
                        wire.write(json.dumps({'time': time.time(), 'session': client.session_id, 'message': value}) + '\n')
                    return receive(value)
                client.receive = traced_receive
                return client
            (output / 'native-wire.jsonl').write_text('')
            bridge.ipc_factory = traced_client
            bridge.connection_workspace = {'id': 'f' * 32, 'name': '测试电脑', 'backend': 'codex-cli'}
            bridge.workspace_directory = root / 'workspace'; bridge.workspace_directory.mkdir()
            bridge.workspace = Workspace(bridge)
            lifecycle = BridgeLifecycle(bridge); bridge.lifecycle = lifecycle
            assert lifecycle.configure(True)['enabled']
            lifecycle.start()
            bridge.workspace.start()
            # Start an ordinary CLI, without --remote. It must create and own the discoverable thread.
            terminal = Terminal(args.codex, env, work, None, None, output / 'cli-terminal.log', 'SEED')
            row = wait(lambda: next(iter(bridge.catalog.list()), None), 'ordinary CLI session discovered', 30)
            tid = row['id']; report['threadId'] = tid
            wait(lambda: completed('SEED'), 'CLI seed completion')
            check('ordinary CLI session discovered through managed daemon')
            cert, key = root / 'localhost.pem', root / 'localhost-key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
                '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1', '-addext', 'basicConstraints=critical,CA:TRUE',
                '-keyout', str(key), '-out', str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['xcrun', 'simctl', 'keychain', args.simulator, 'add-root-cert', str(cert)], check=True)
            os.environ['SSL_CERT_FILE'] = str(cert)
            config = {'publicUrl': 'https://localhost', 'account': password_record('test-owner', 'c' * 40), 'devices': {
                'cli-fixture': {'deviceToken': 'd' * 40, 'apiToken': 'a' * 40, 'members': {'owner': list(CAPABILITIES)}, 'ownerUserId': 'owner'}}}
            if args.workspace_connections:
                config['devices']['desktop-fixture'] = {'deviceToken': 'e' * 40, 'apiToken': 'b' * 40, 'members': {'owner': ['view']}, 'ownerUserId': 'owner'}
                report['limitations'].append('Desktop channel uses a protocol fixture, not the native desktop application')
            if args.shared_binding:
                config['devices'].pop('cli-fixture')
                config['devices']['desktop-fixture']['members']['owner'] = list(CAPABILITIES)
            console = ConsoleServer(('127.0.0.1', 0), config); console.RequestHandlerClass = Handler
            url = f'https://localhost:{console.server_port}'; console.origin = console.public_url = url
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
            console.socket = context.wrap_socket(console.socket, server_side=True)
            threading.Thread(target=console.serve_forever, daemon=True).start()
            cli_config = {'enabled': True, 'url': url.replace('https:', 'wss:') + '/device',
                          'deviceId': 'cli-fixture', 'token': 'd' * 40, 'control': True}
            workspace_description = {'id': 'f' * 32, 'name': '测试电脑', 'backend': 'desktop-ipc'}
            if args.shared_binding:
                from carryon.services import register
                from carryon.workspaces.connections import descriptor
                from carryon.cloud.cloud_manager import CloudManager
                from carryon.accounts.onboarding import exchange
                os.environ['CARRYON_REGISTRY_DIR'] = str(root / 'registry')
                source_dir, target_dir = root / 'desktop-local', root / 'cli-local'
                source_dir.mkdir(); target_dir.mkdir()
                source_row = register(source_dir, name='测试电脑', backend='desktop-ipc', codex_home=home)
                target_row = register(target_dir, backend='codex-cli', codex_home=home)
                workspace_description = descriptor(source_row)
                console.config['devices']['desktop-fixture']['workspace'] = workspace_description
                CloudManager(None, source_dir).configure({**cli_config, 'deviceId':'desktop-fixture', 'token':'e'*40}, start=False)
                binding_id = next(iter(CloudManager.saved_bindings(source_dir)))
                preview = exchange(target_dir, {'action':'share-preview', 'sourceDirectory':str(source_dir), 'sourceBindingId':binding_id})
                assert len(console.config['devices']) == 1
                exchange(target_dir, {'action':'share-confirm', 'shareConfirmation':preview['shareConfirmation'], 'confirmed':True, 'autoStart':False})
                cli_config = next(iter(CloudManager.saved_bindings(target_dir).values()))
                assert not console.binding_invites.entries
                assert 'members' not in console.config['devices'][cli_config['deviceId']]
                bridge.connection_workspace = descriptor(target_row)
                check('native confirmation adds CLI without second phone scan or copied grants')
            connector = CloudConnector(bridge, config=cli_config, binding_id=None)
            connector.start(); wait(lambda: connector.status()['connected'], 'TLS device connector', 20)
            if args.workspace_connections:
                from test_cloud import IPC, Catalog
                from carryon.sessions.bridge import Bridge
                class DesktopCatalog(Catalog):
                    def list(self, *_): return [{'id': tid, 'title': 'Desktop fixture', 'cwd': str(work)}]
                desktop_bridge = Bridge('fixture', DesktopCatalog(), Journal(root / 'desktop-jobs.sqlite'), IPC)
                desktop_bridge.connection_workspace = workspace_description
                desktop_bridge.enable()
                desktop_connector = CloudConnector(desktop_bridge, config={'enabled': True, 'url': url.replace('https:', 'wss:') + '/device',
                    'deviceId': 'desktop-fixture', 'token': 'e' * 40, 'control': False}, binding_id=None)
                desktop_connector.start(); wait(lambda: desktop_connector.status()['connected'], 'second TLS connector', 20)
            documents = container / 'Documents'; documents.mkdir(exist_ok=True)
            (documents / 'cli-config.json').write_text(json.dumps({'url': url, 'password': 'c' * 40, 'threadId': tid, 'workspaceConnections': args.workspace_connections, 'sharedBinding': args.shared_binding, 'cliDeviceId': cli_config['deviceId']}))
            result = documents / 'cli-result.json'; before = result.stat().st_mtime_ns if result.exists() else None
            subprocess.run(['xcrun', 'simctl', 'launch', '--terminate-running-process', '--stdout=' + str(output / 'simulator.log'),
                '--stderr=' + str(output / 'simulator-errors.log'), args.simulator, BUNDLE], check=True, timeout=90)
            wait(lambda: result.exists() and result.stat().st_mtime_ns != before, 'iOS full-chain result', 240)
            report['phone'] = json.loads(result.read_text()); report['passed'] = report['phone']['passed']
            shutil.copy2(documents / 'cli-history.json', output / 'phone-history.json')
            (output / 'bridge-history.json').write_text(json.dumps(bridge.history(tid), indent=2))
            (output / 'native-current.json').write_text(json.dumps(bridge.ipc.current(tid), indent=2))
            for screenshot in documents.glob('cli-*.png'): shutil.copy2(screenshot, output / screenshot.name)
        except Exception as exc:
            report['error'] = repr(exc)
            print('FAILED', repr(exc), flush=True)
        finally:
            for gate in fixture.gates.values(): gate.set()
            if terminal: terminal.close()
            if desktop_connector: desktop_connector.stop()
            if desktop_bridge:
                desktop_bridge.disable()
                desktop_bridge.journal.conn.close()
            if connector: connector.stop()
            if bridge and hasattr(bridge, 'workspace'): bridge.workspace.close()
            if lifecycle: lifecycle.close()
            if console: console.shutdown(); console.server_close()
            if model: model.shutdown(); model.server_close()
            with suppress(Exception): report['daemonStop'] = daemon('stop').stdout
            report['modelCalls'] = fixture.calls
            if old_registry is None: os.environ.pop('CARRYON_REGISTRY_DIR', None)
            else: os.environ['CARRYON_REGISTRY_DIR'] = old_registry
            if old_ca is None: os.environ.pop('SSL_CERT_FILE', None)
            else: os.environ['SSL_CERT_FILE'] = old_ca
            report['sourceCommit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
            (output / 'result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
            print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__': sys.exit(main())
