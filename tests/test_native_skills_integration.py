"""Skill discovery/input against a private native home and localhost model."""
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
from carryon.sessions.skills import discover
from carryon.store import Journal


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeSkillsIntegration(unittest.TestCase):
    def test_direct_skills(self): self.run_case(False)
    def test_owner_skills(self): self.run_case(True)

    def run_case(self, owned):
        model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='carryon-native-skills-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            skill = home / 'skills' / 'fixture-skill' / 'SKILL.md'; skill.parent.mkdir(parents=True)
            skill.write_text('---\nname: fixture-skill\ndescription: Isolated skill fixture\n---\nRespond briefly.\n')
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
                inventory = discover(bridge, tid)
                found = next(item for item in inventory['skills'] if item['name'] == 'fixture-skill')
                self.assertTrue(found['enabled']); self.assertEqual(Path(found['path']).resolve(), skill.resolve())
                selection = {key: found[key] for key in ('name', 'path')}
                job = bridge.compose(tid, 'skill-once', '', skills=[selection])
                wait_until(lambda: journal.get('skill-once')['state'] not in ('preparing', 'dispatching'))
                job = journal.get('skill-once'); self.assertEqual(job['state'], 'accepted', job)
                if owned:
                    wait_until(lambda: manager.entries[tid].get('suspended') is True)
                    inspector = AppServer(home, runtime_directory=root / 'inspector'); inspector.connect(); inspector.snapshot(tid)
                    reader = inspector
                else:
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid))); reader = runtime
                page = reader.rpc('thread/turns/list', {'threadId': tid, 'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
                user = next(item for item in page['data'][-1]['items'] if item['type'] == 'userMessage')
                self.assertIn({'type': 'skill', **selection}, user['content'])
                self.assertEqual(bridge.compose(tid, 'skill-once', '', skills=[selection]), job)
            except Exception as exc:
                logs = '\n'.join(str(path.relative_to(root)) + '\n' + path.read_text(errors='replace') for path in root.rglob('app-server.log'))
                self.fail(str(exc) + '\nIsolated native diagnostics:\n' + logs)
            finally:
                if inspector: inspector.close()
                if follower: follower.close()
                if owned: bridge.shutdown()
                else: bridge.disable()
                runtime.close(); journal.conn.close(); model.shutdown(); model.server_close()
