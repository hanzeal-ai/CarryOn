"""Native goal lifecycle against a private native home and localhost model."""
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
from carryon.desktop_ipc.ipc import DesktopIPC
from carryon.errors import IPCError
from carryon.owner.integration import OwnerBridge
from carryon.owner.manager import OwnerManager
from carryon.sessions.catalog import Catalog
from carryon.sessions.operations import submit
from carryon.codex_protocol.goals import discover
from carryon.store import Journal


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeGoalsIntegration(unittest.TestCase):
    def test_direct_goals(self): self.run_case(False)
    def test_owner_goals(self): self.run_case(True)

    def run_case(self, owned):
        class CountedModel(Model):
            calls = 0
            def do_POST(self):
                type(self).calls += 1
                super().do_POST()
        model = ThreadingHTTPServer(('127.0.0.1', 0), CountedModel)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='carryon-native-goals-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
                '[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) +
                '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            journal = Journal(root / 'jobs.sqlite'); follower = None; inspector = None
            if owned:
                follower = DesktopIPC('unused'); follower.client_id = 'fixture-desktop'
                class Transport(DesktopIPC):
                    def connect(self):
                        self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                        for ipc in (self, follower):
                            threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
                    def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
                catalog = Catalog(home); manager = OwnerManager(home, root / 'owner', catalog, transport_factory=Transport)
                bridge = OwnerBridge('unused', catalog, journal, owner_directory=root / 'owner')
                bridge.ipc = follower; bridge.enabled = True; bridge.owner_service = manager
                runtime = AppServer(home, runtime_directory=root / 'runtime'); runtime.connect()
            else:
                bridge = AppServerBridge(home, journal); bridge.enable(); runtime = bridge.ipc
            try:
                thread = runtime.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda write: write())
                tid = thread['id']
                if owned:
                    # Native empty threads are not persisted in the catalog until
                    # their first turn. Adopt the empty baseline, then seed it as
                    # in the fork/edit fixtures before using catalog-backed APIs.
                    manager.adopt(tid, runtime)
                    runtime.start(tid, 'fixture seed', 'app-server', 'seed', lambda write: write())
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid)))
                    wait_until(lambda: bool(catalog.list())); follower.snapshot(tid)
                self.assertIsNone(discover(bridge, tid)['goal'])
                create = {'action': 'goal-set', 'requestId': 'goal-create',
                          'objective': 'Complete the private fixture without tools.', 'status': 'active', 'tokenBudget': 100000}
                started = submit(bridge, tid, create)
                self.assertEqual(started['state'], 'completed', started)
                wait_until(lambda: len(runtime.current(tid)['turns']) >= 3)
                if owned:
                    self.assertTrue(runtime.connected)
                    self.assertFalse(manager.entries[tid].get('suspended', False))
                self.assertEqual(discover(bridge, tid)['goal']['status'], 'active')
                paused = submit(bridge, tid, {'action': 'goal-pause', 'requestId': 'goal-pause'})
                self.assertEqual(paused['state'], 'completed', paused)
                self.assertEqual(paused['result']['goal']['status'], 'paused')
                if owned:
                    wait_until(lambda: manager.entries[tid].get('suspended') is True)
                    inactive_runtime = manager.entries[tid]['runtime']
                    calls = CountedModel.calls
                    self.assertEqual(discover(bridge, tid)['goal']['status'], 'paused')
                    paused_again = submit(bridge, tid, {'action': 'goal-pause', 'requestId': 'suspended-pause'})
                    self.assertEqual(paused_again['state'], 'completed', paused_again)
                    cleared_idle = submit(bridge, tid, {'action': 'goal-clear', 'requestId': 'suspended-clear'})
                    self.assertEqual(cleared_idle['state'], 'completed', cleared_idle)
                    self.assertIsNone(discover(bridge, tid)['goal'])
                    self.assertTrue(manager.entries[tid]['suspended'])
                    self.assertIs(manager.entries[tid]['runtime'], inactive_runtime)
                    self.assertFalse(inactive_runtime.connected)
                    self.assertEqual(CountedModel.calls, calls, 'read/pause/clear must not resume the native task')
                else: wait_until(lambda: runtime.queue_idle(runtime.current(tid)))
                resumed = submit(bridge, tid, {'action': 'goal-set', 'requestId': 'goal-resume', 'status': 'active',
                    **({'objective': create['objective']} if owned else {})})
                self.assertEqual(resumed['state'], 'completed', resumed)
                if owned: runtime = manager.entries[tid]['runtime']
                self.assertEqual(discover(bridge, tid)['goal']['status'], 'active')
                cleared = submit(bridge, tid, {'action': 'goal-clear', 'requestId': 'goal-clear'})
                self.assertEqual(cleared['state'], 'completed', cleared)
                self.assertTrue(cleared['result']['cleared'])
                self.assertEqual(submit(bridge, tid, create), started)
                if owned: wait_until(lambda: manager.entries[tid].get('suspended') is True)
                else:
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid)))
                    self.assertIsNone(discover(bridge, tid)['goal'])
            except Exception as exc:
                logs = '\n'.join(str(path.relative_to(root)) + '\n' + path.read_text(errors='replace') for path in root.rglob('app-server.log'))
                self.fail(str(exc) + '\nIsolated native diagnostics:\n' + logs)
            finally:
                if inspector: inspector.close()
                if follower: follower.close()
                if owned: bridge.shutdown()
                else: bridge.disable()
                runtime.close(); journal.conn.close(); model.shutdown(); model.server_close()
