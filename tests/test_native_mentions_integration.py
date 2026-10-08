"""Real installed local plugin inventory and mention delivery; localhost model only.

CODEX_HOME isolates installed plugins; discovery may also list machine marketplace
metadata, so assertions select only the temporary fixture identity.
"""
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
from carryon.sessions.mentions import discover
from carryon.store import Journal


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeMentionsIntegration(unittest.TestCase):
    def test_direct_mentions(self): self.run_case(False)
    def test_owner_mentions(self): self.run_case(True)

    def test_direct_creation_references(self): self.run_case(False, creation=True)
    def test_owner_creation_references(self): self.run_case(True, creation=True)

    def run_case(self, owned, creation=False):
        model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='carryon-native-mentions-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            import json
            marketplace = root / '.agents' / 'plugins' / 'marketplace.json'
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps({'name': 'carryon-fixture', 'plugins': [{'name': 'fixture', 'source': {'source': 'local', 'path': './fixture'}}]}))
            manifest = root / 'fixture' / '.codex-plugin' / 'plugin.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'name': 'fixture', 'version': '1.0.0', 'description': 'Private fixture'}))
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
                if creation:
                    bridge.workspace_directory = root / 'workspace'
                    from carryon.workspaces.workspace import Workspace
                    bridge.workspace = Workspace(bridge)
                    if owned: manager.bus.connect()
                    self.creation_case(bridge, runtime, root, home, marketplace, owned)
                    return
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
                runtime.rpc('plugin/install', {'pluginName': 'fixture', 'marketplacePath': str(marketplace)})
                inventory = discover(bridge, tid)
                found = next(item for item in inventory['mentions'] if item['path'] == 'plugin://fixture@carryon-fixture')
                self.assertTrue(found['enabled'])
                selection = {key: found[key] for key in ('name', 'path')}
                job = bridge.compose(tid, 'mention-once', '', mentions=[selection])
                wait_until(lambda: journal.get('mention-once')['state'] not in ('preparing', 'dispatching'))
                job = journal.get('mention-once'); self.assertEqual(job['state'], 'accepted', job)
                if owned:
                    wait_until(lambda: manager.entries[tid].get('suspended') is True)
                    inspector = AppServer(home, runtime_directory=root / 'inspector'); inspector.connect(); inspector.snapshot(tid)
                    reader = inspector
                else:
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid))); reader = runtime
                page = reader.rpc('thread/turns/list', {'threadId': tid, 'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
                user = next(item for item in page['data'][-1]['items'] if item['type'] == 'userMessage')
                self.assertIn({'type': 'mention', **selection}, user['content'])
                self.assertEqual(bridge.compose(tid, 'mention-once', '', mentions=[selection]), job)
                if not owned:
                    from carryon.sessions.operations import submit
                    queue = bridge.queue(tid, authoritative=True)
                    queued = submit(bridge, tid, {'action': 'queue-add', 'requestId': 'mention-queue',
                        'prompt': 'queued reference', 'mentions': [selection], 'queueFingerprint': queue['fingerprint']})
                    self.assertEqual(queued['state'], 'completed', queued)
                    def last_turn():
                        rows = runtime.rpc('thread/turns/list', {'threadId': tid, 'sortDirection': 'desc', 'limit': 1, 'itemsView': 'full'})['data']
                        return rows[0] if rows else None
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid)) and last_turn()['id'] != page['data'][-1]['id'] and last_turn()['status'] == 'completed' and any(item['type'] == 'userMessage' for item in last_turn()['items']))
                    queued_turn = last_turn()
                    queued_user = next(item for item in queued_turn['items'] if item['type'] == 'userMessage')
                    self.assertIn({'type': 'mention', **selection}, queued_user['content'])
                    edited = submit(bridge, tid, {'action': 'edit', 'requestId': 'mention-edit',
                        'turnId': queued_turn['id'], 'prompt': 'edited reference', 'confirmed': True})
                    self.assertEqual(edited['state'], 'completed', edited)
                    wait_until(lambda: runtime.queue_idle(runtime.current(tid)))
                    edited_turn = last_turn()
                    edited_user = next(item for item in edited_turn['items'] if item['type'] == 'userMessage')
                    self.assertIn({'type': 'mention', **selection}, edited_user['content'])
                    self.assertEqual(edited_user['content'][0]['text'], 'edited reference')
                    runtime.rpc('plugin/uninstall', {'pluginId': 'fixture@carryon-fixture'})
                    revoked = bridge.compose(tid, 'mention-revoked', '', mentions=[selection])
                    self.assertEqual(revoked['state'], 'failed', revoked)
                    self.assertNotIn('turnId', revoked)
                    rejected_edit = submit(bridge, tid, {'action': 'edit', 'requestId': 'mention-edit-revoked',
                        'turnId': edited_turn['id'], 'prompt': 'must not revert', 'confirmed': True})
                    self.assertEqual(rejected_edit['state'], 'failed', rejected_edit)
                    self.assertEqual(last_turn()['id'], edited_turn['id'])

            except Exception as exc:
                logs = '\n'.join(str(path.relative_to(root)) + '\n' + path.read_text(errors='replace') for path in root.rglob('app-server.log'))
                self.fail(str(exc) + '\nIsolated native diagnostics:\n' + logs)
            finally:
                if inspector: inspector.close()
                if follower: follower.close()
                if owned: bridge.shutdown()
                else: bridge.disable()
                runtime.close(); journal.conn.close(); model.shutdown(); model.server_close()

    def creation_case(self, bridge, runtime, root, home, marketplace, owned):
        import json
        from carryon.sessions.creation_references import discover as discover_creation
        from carryon.sessions.creation import submit as owner_create
        from carryon.app_server.app_creation import submit as direct_create
        from carryon.workspaces.workspace import project_identity
        from carryon.errors import BridgeError
        skill = home / 'skills' / 'fixture-skill' / 'SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: fixture-skill\ndescription: Local fixture\n---\nSay fixture.\n')
        if not owned: runtime.rpc('marketplace/add', {'source': str(root)})
        runtime.rpc('plugin/install', {'pluginName': 'fixture', 'marketplacePath': str(marketplace)})
        project_id = None
        if owned:
            native = runtime.rpc('project/create', {'idempotencyKey': 'fixture-project', 'name': 'fixture', 'roots': [{'path': str(root)}]})['project']
            (home / '.codex-global-state.json').write_text(json.dumps({'local-projects': {native['id']: {'rootPaths': [str(root)]}}}))
            project_id = project_identity(str(root), native_id=native['id'])[0]
        catalog = discover_creation(bridge, project_id)
        selected_skill = next(row for row in catalog['skills'] if row['name'] == 'fixture-skill')
        selected_plugin = next(row for row in catalog['mentions'] if row['path'] == 'plugin://fixture@carryon-fixture')
        refs = {'skills': [{k: selected_skill[k] for k in ('name', 'path')}], 'mentions': [{k: selected_plugin[k] for k in ('name', 'path')}]}
        create = owner_create if owned else direct_create
        configuration = {'model': 'gpt-5.5', 'effort': 'high', 'approvalPolicy': 'never', 'collaborationMode': {'mode': 'plan', 'settings': {'model': 'gpt-5.5', 'reasoning_effort': 'high', 'developer_instructions': None}}}
        job = create(bridge, 'reference-create', '', project_id, settings=configuration, **refs)
        wait_until(lambda: bridge.journal.get(job['id'])['state'] not in ('preparing', 'dispatching'))
        job = bridge.journal.get(job['id']); self.assertEqual(job['state'], 'completed' if owned else 'accepted', job)
        self.assertEqual(create(bridge, job['id'], '', project_id, settings=configuration, **refs)['createdThreadId'], job['createdThreadId'])
        with self.assertRaises(BridgeError): create(bridge, job['id'], '', project_id, mentions=refs['mentions'])
        tid = job['createdThreadId']
        reader = bridge.owner_service.entries[tid]['runtime'] if owned else runtime
        def turn_done():
            state = reader.current(tid)
            return state and any(turn.get('status') == 'completed' for turn in state.get('turns', []))
        if not owned: wait_until(turn_done)
        inspector = AppServer(home, runtime_directory=root / 'creation-inspector') if owned else runtime
        if owned:
            wait_until(lambda: bridge.owner_service.entries[tid].get('suspended') is True)
            inspector.connect(); inspector.snapshot(tid)
        try:
            page = inspector.rpc('thread/turns/list', {'threadId': tid, 'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
            self.assertEqual(len(page['data']), 1)
            self.assertEqual(page['data'][0]['status'], 'completed')
            contexts = [row['payload'] for path in home.rglob('*.jsonl') for line in path.read_text().splitlines() if (row := json.loads(line)).get('type') == 'turn_context' and row.get('payload', {}).get('turn_id') == page['data'][0]['id']]
            self.assertTrue(contexts, 'persisted native first-turn context')
            context = contexts[-1]
            self.assertEqual(context['approval_policy'], 'never')
            self.assertEqual(context['collaboration_mode']['mode'], 'plan')
            self.assertEqual(context['effort'], 'high')
            user = next(item for item in page['data'][0]['items'] if item['type'] == 'userMessage')
            self.assertIn({'type': 'skill', **refs['skills'][0]}, user['content'])
            self.assertIn({'type': 'mention', **refs['mentions'][0]}, user['content'])
            inspector.rpc('plugin/uninstall', {'pluginId': 'fixture@carryon-fixture'})
            denied = create(bridge, 'revoked-reference-create', '', project_id, **refs)
            wait_until(lambda: bridge.journal.get(denied['id'])['state'] not in ('preparing', 'dispatching'))
            denied = bridge.journal.get(denied['id']); self.assertEqual(denied['state'], 'uncertain', denied)
            self.assertNotIn('turnId', denied)
            self.assertEqual(create(bridge, denied['id'], '', project_id, **refs)['createdThreadId'], denied['createdThreadId'])
        finally:
            if owned: inspector.close()
