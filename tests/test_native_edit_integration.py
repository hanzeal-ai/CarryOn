"""Real revert/start and Owner integration, with a private home and local model."""
import os
import socket
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from run_appserver_regression import Model, wait_until
from carryon.app_server.app_server import AppServer
from carryon.app_server.app_server_bridge import AppServerBridge
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError
from carryon.owner.integration import OwnerBridge
from carryon.owner.manager import OwnerManager
from carryon.sessions.catalog import Catalog
from carryon.sessions.operations import submit
from carryon.store import Journal


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeEditIntegration(unittest.TestCase):
    def test_independent_revert_start(self): self.run_case(False)

    def test_owner_revert_start(self): self.run_case(True)

    def run_case(self, owned):
        model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='carryon-native-edit-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
                '[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) +
                '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            journal = Journal(root / 'jobs.sqlite'); follower = None
            if owned:
                follower = DesktopIPC('unused'); follower.client_id = 'fixture-desktop'
                class OwnerTransport(DesktopIPC):
                    def connect(self):
                        self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                        for ipc in (self, follower):
                            threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
                    def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
                catalog = Catalog(home)
                manager = OwnerManager(home, root / 'owner', catalog, transport_factory=OwnerTransport)
                bridge = OwnerBridge('unused', catalog, journal, owner_directory=root / 'owner')
                bridge.ipc = follower; bridge.enabled = True; bridge.owner_service = manager
                runtime = AppServer(home, runtime_directory=root / 'runtime')
                try: runtime.connect()
                except Exception as exc:
                    self.fail(str(exc) + '\n' + (root / 'runtime' / 'app-server.log').read_text())
            else:
                bridge = AppServerBridge(home, journal); bridge.enable(); runtime = bridge.ipc
            inspector = None
            try:
                thread = runtime.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda write: write())
                tid = thread['id']
                if owned: manager.adopt(tid, runtime)
                originals = []
                for i in range(2):
                    originals.append(runtime.start(tid, 'fixture original ' + str(i), 'app-server', 'original-' + str(i), lambda write: write())['id'])
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid)))
                if owned:
                    wait_until(lambda: bool(catalog.list())); follower.snapshot(tid)
                mode = {'mode': 'plan', 'settings': {'model': 'gpt-5.5', 'reasoning_effort': 'high', 'developer_instructions': None}}
                settings_job = submit(bridge, tid, {'action': 'settings', 'requestId': 'native-settings-once',
                    'settings': {'model': 'gpt-5.5', 'effort': 'high', 'collaborationMode': mode}})
                self.assertEqual(settings_job['state'], 'completed', settings_job)
                wait_until(lambda: runtime.current(tid).get('latestThreadSettings', {}).get('collaborationMode', {}).get('mode') == 'plan')
                self.assertEqual(runtime.current(tid)['latestThreadSettings']['effort'], 'high')
                data = {'action': 'edit', 'requestId': 'native-edit-once', 'turnId': originals[-1],
                    'prompt': 'fixture replacement', 'confirmed': True}
                job = submit(bridge, tid, data)
                self.assertEqual(job['state'], 'completed', job)
                if owned:
                    # Completion releases the original writer. Verify persisted
                    # history with a separate runtime, not its discarded cache.
                    wait_until(lambda: manager.entries.get(tid, {}).get('suspended') is True)
                    self.assertFalse(runtime.connected)
                    self.assertEqual(manager.entries[tid].get('in_flight', 0), 0)
                    inspector = AppServer(home, runtime_directory=root / 'inspector')
                    inspector.connect(); inspector.snapshot(tid)
                    reader = inspector
                else:
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid)))
                    reader = runtime
                page = reader.rpc('thread/turns/list', {'threadId': tid, 'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
                self.assertEqual([t['id'] for t in page['data']], [originals[0], job['turnId']])
                user = next(i for i in page['data'][-1]['items'] if i['type'] == 'userMessage')
                self.assertEqual(user['clientId'], job['clientMessageId'])
                self.assertEqual(user['content'][0]['text'], 'fixture replacement')
                self.assertEqual(submit(bridge, tid, data), job)
            finally:
                if inspector: inspector.close()
                if follower: follower.close()
                if owned: bridge.shutdown()
                else: bridge.disable()
                runtime.close(); journal.conn.close()
                model.shutdown(); model.server_close()
