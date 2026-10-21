"""Project API -> temporary app-server -> Owner IPC -> real local-fixture turn."""
import json
import socket
import sys
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from run_appserver_regression import Model, wait_until
from carryon.app_server.app_server import AppServer
from carryon.sessions.catalog import Catalog
from carryon.desktop_ipc.ipc import DesktopIPC
from carryon.errors import IPCError
from carryon.owner.integration import OwnerBridge
from carryon.owner.manager import OwnerManager
from carryon.routes.remote_scope import scoped_dispatch, request_key
from carryon.store import Journal
from carryon.workspaces.workspace import project_identity, Workspace


def main():
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='carryon-creation-regression-') as directory:
            root = Path(directory).resolve(); home = root / 'codex'; home.mkdir()
            project_root = root / 'project'; project_root.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) + '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            setup = AppServer(home, runtime_directory=root / 'setup')
            try:
                setup.connect()
                project = setup.rpc('project/create', {'idempotencyKey': 'fixture-project', 'name': 'fixture',
                                                       'roots': [{'path': str(project_root)}]})['project']
            finally: setup.close()
            (home / '.codex-global-state.json').write_text(json.dumps({'local-projects': {
                'obsolete-desktop-id': {'name': 'Old desktop name', 'rootPaths': [str(root)]}}}))
            follower = DesktopIPC('unused'); follower.client_id = 'fixture-desktop'
            class OwnerTransport(DesktopIPC):
                def connect(self):
                    self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                    for ipc in (self, follower):
                        threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
                def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
            journal = Journal(root / 'jobs.sqlite')
            bridge = OwnerBridge('unused', Catalog(home), journal, owner_directory=root / 'owner')
            manager = OwnerManager(home, root / 'owner', bridge.catalog, transport_factory=OwnerTransport)
            manager.bus.connect(); bridge.ipc = follower; bridge.enabled = True; bridge.owner_service = manager
            observed = {}
            follower.on_change = lambda: observed.update({tid: follower.current(tid) for tid in list(follower.snapshots)})
            try:
                assert bridge.catalog.list() == []
                bridge.workspace = Workspace(bridge)
                bridge.workspace.catalog_refresh()
                status, listing = scoped_dispatch(bridge, 'GET', '/api/projects', None, True, 'fixture-binding')
                expected = project_identity(str(project_root), native_id=project['id'])[0]
                assert status == 200 and len(listing['projects']) == 1, listing
                selected = listing['projects'][0]
                assert selected['id'] == expected and selected['name'] == 'fixture' and selected['total'] == 0, selected
                body = {'requestId': 'fixture-create-request', 'projectId': selected['id'],
                        'prompt': 'fixture new task'}
                status, job = scoped_dispatch(bridge, 'POST', '/api/threads', body, True, 'fixture-binding')
                assert status == 202
                key = request_key('fixture-binding', body['requestId'])
                wait_until(lambda: journal.get(key)['state'] not in ('preparing', 'dispatching'))
                job = journal.get(key); assert job['state'] == 'completed', job
                tid = job['createdThreadId']; turn_id = job['turnId']
                # Same request must not create another thread or submit another turn.
                duplicate = scoped_dispatch(bridge, 'POST', '/api/threads', body, True, 'fixture-binding')[1]
                assert duplicate['createdThreadId'] == tid
                wait_until(lambda: any(t['turnId'] == turn_id and t['status'] == 'completed'
                                       for t in observed.get(tid, {}).get('turns', [])))
                state = observed[tid]; assert state['executionBackend'] == 'carryon-owner'
                assert len(state['turns']) == 1
                assert any(i.get('text') == 'fixture response' for i in state['turns'][0]['items'])
                rows = bridge.catalog.list(); assert len(rows) == 1, rows
                assert rows[0]['nativeProjectId'] == project['id'] and rows[0]['cwd'] == str(project_root)
                free_body = {'requestId': 'fixture-projectless-request', 'prompt': 'fixture projectless task'}
                status, free_job = scoped_dispatch(bridge, 'POST', '/api/threads', free_body, True, 'fixture-binding')
                assert status == 202
                free_key = request_key('fixture-binding', free_body['requestId'])
                wait_until(lambda: journal.get(free_key)['state'] not in ('preparing', 'dispatching'))
                free_job = journal.get(free_key); assert free_job['state'] == 'completed', free_job
                free_tid = free_job['createdThreadId']
                wait_until(lambda: any(t['status'] == 'completed' for t in observed.get(free_tid, {}).get('turns', [])))
                free_state = observed[free_tid]
                assert any(i.get('text') == 'fixture response' for i in free_state['turns'][0]['items'])
                free_row = next(r for r in bridge.catalog.list() if r['id'] == free_tid)
                assert free_row['projectless'], free_row
                with bridge.catalog.connection() as conn:
                    assert conn.execute('SELECT project_id FROM threads WHERE id=?', (free_tid,)).fetchone()[0] is None
                assert Path(free_row['cwd']).is_relative_to(root / 'owner' / 'tasks'), free_row
                assert scoped_dispatch(bridge, 'POST', '/api/threads', free_body, True, 'fixture-binding')[1]['createdThreadId'] == free_tid
                follower._write({'type': 'broadcast', 'method': 'thread-stream-following-changed',
                    'version': 1, 'sourceClientId': follower.client_id, 'targetClientIds': ['fixture-owner'],
                    'params': {'hostId': 'local', 'conversationId': tid, 'following': False}})
                wait_until(lambda: tid not in manager.entries)
                follower._write({'type': 'broadcast', 'method': 'thread-stream-following-changed',
                    'version': 1, 'sourceClientId': follower.client_id, 'targetClientIds': ['fixture-owner'],
                    'params': {'hostId': 'local', 'conversationId': free_tid, 'following': False}})
                wait_until(lambda: free_tid not in manager.entries)
                archiver = AppServer(home, runtime_directory=root / 'archiver')
                try:
                    archiver.connect()
                    archiver.rpc('thread/archive', {'threadId': tid})
                    archiver.rpc('thread/archive', {'threadId': free_tid})
                    assert bridge.catalog.list() == []
                finally: archiver.close()
                print(json.dumps({'passed': True, 'checks': ['create with zero existing conversations',
                    'native project identity despite conflicting desktop JSON', 'empty project listing', 'cloud request scoping', 'temporary runtime adoption',
                    'IPC owner task delivery', 'real streamed turn', 'duplicate request', 'automatic release',
                    'native archive after release', 'projectless real thread and completed response',
                    'projectless native membership and private cwd', 'projectless idempotency']}))
            finally: bridge.shutdown(); journal.conn.close()
    finally: model.shutdown(); model.server_close()


if __name__ == '__main__': main()
