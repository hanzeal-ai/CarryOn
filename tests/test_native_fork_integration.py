"""Opt-in cross-runtime native fork, private CODEX_HOME and localhost model."""
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
from carryon.sessions.forking import submit
from carryon.store import Journal


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeForkIntegration(unittest.TestCase):
    def test_dispatch_catalog_and_owner_load(self):
        model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='carryon-native-fork-owner-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
                '[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) +
                '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            journal = Journal(root / 'jobs.sqlite')
            follower = DesktopIPC('unused'); follower.client_id = 'fixture-desktop'
            class Transport(DesktopIPC):
                def connect(self):
                    self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                    for ipc in (self, follower):
                        threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
                def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
            catalog = Catalog(home)
            manager = OwnerManager(home, root / 'owner', catalog, transport_factory=Transport)
            bridge = OwnerBridge('unused', catalog, journal, owner_directory=root / 'owner')
            bridge.ipc = follower; bridge.enabled = True; bridge.owner_service = manager
            source = AppServer(home, runtime_directory=root / 'source')
            independent = AppServerBridge(home, journal)
            try:
                source.connect()
                thread = source.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda write: write())
                tid = thread['id']; manager.adopt(tid, source)
                turn = source.start(tid, 'fixture source', 'app-server', 'source-one', lambda write: write())['id']
                wait_until(lambda: source.queue_idle(source.current(tid)))
                wait_until(lambda: bool(catalog.list())); follower.snapshot(tid)
                # Exercise both dispatch branches against the same persisted source;
                # the independent bridge borrows the runtime only for this fixture.
                independent.ipc = source; independent.enabled = True
                for number, sender in enumerate((bridge, independent)):
                    data = {'requestId': 'fork-production-' + str(number), 'lastTurnId': turn}
                    submit(sender, tid, data)
                    wait_until(lambda: journal.get(data['requestId'])['state'] not in ('preparing', 'dispatching'))
                    job = journal.get(data['requestId']); self.assertEqual(job['state'], 'completed', job)
                    child = job['createdThreadId']
                    wait_until(lambda: any(row['id'] == child for row in catalog.list()))
                    self.assertEqual(Path(catalog.get(child)['cwd']).resolve(), root.resolve())
                    # Wait for the short-lived fork writer to close before loading.
                    manager.load(child)
                    child_runtime = manager.entries[child]['runtime']
                    self.assertIsNot(child_runtime, source)
                    self.assertEqual([t['turnId'] for t in child_runtime.current(child)['turns']], [turn])
                    self.assertEqual(child_runtime.current(child)['threadRuntimeStatus']['type'], 'idle')
                    self.assertEqual(submit(sender, tid, data), job)
                    self.assertEqual(len(source.current(tid)['turns']), 1)
            except Exception as exc:
                logs = '\n'.join(str(path.relative_to(root)) + '\n' + path.read_text(errors='replace')
                    for path in root.rglob('app-server.log'))
                self.fail(str(exc) + '\nIsolated native diagnostics:\n' + logs)
            finally:
                follower.close(); bridge.shutdown(); source.close(); journal.conn.close()
                model.shutdown(); model.server_close()

    def test_cross_runtime_fork_preserves_history_without_starting(self):
        model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='carryon-native-fork-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
                '[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) +
                '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            source = AppServer(home, runtime_directory=root / 'source')
            creator = AppServer(home, runtime_directory=root / 'creator')
            reader = AppServer(home, runtime_directory=root / 'reader')
            try:
                source.connect(); creator.connect()
                thread = source.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda write: write())
                tid = thread['id']; ids = []
                for i in range(2):
                    ids.append(source.start(tid, 'fixture source ' + str(i), 'app-server', 'source-' + str(i), lambda write: write())['id'])
                    wait_until(lambda: source.queue_idle(source.current(tid)))
                result = creator.rpc('thread/fork', {'threadId': tid, 'lastTurnId': ids[0],
                    'excludeTurns': True, 'deferGoalContinuation': True})
                child = result['thread']
                self.assertNotEqual(child['id'], tid)
                self.assertEqual(child['forkedFromId'], tid)
                self.assertEqual(Path(child['cwd']).resolve(), Path(thread['cwd']).resolve())
                self.assertEqual(child['historyMode'], 'paginated')
                self.assertEqual(child['status']['type'], 'idle')
                loaded = creator.rpc('thread/loaded/list', {})['data']
                self.assertIn(child['id'], loaded)
                self.assertNotIn(tid, loaded)
                creator.close()
                # Fork is durable without sending a new prompt. Another runtime
                # can resume it after the fork writer closes.
                reader.connect(); _, state = reader.snapshot(child['id'])
                self.assertEqual([t['turnId'] for t in state['turns']], [ids[0]])
                self.assertEqual(state['threadRuntimeStatus']['type'], 'idle')
                self.assertEqual(len(source.current(tid)['turns']), 2)
            finally:
                reader.close(); creator.close(); source.close(); model.shutdown(); model.server_close()
