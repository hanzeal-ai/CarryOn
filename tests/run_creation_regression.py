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
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError
from carryon.owner.integration import OwnerBridge
from carryon.owner.manager import OwnerManager
from carryon.routes.remote_scope import scoped_dispatch, request_key
from carryon.store import Journal
from carryon.workspaces.workspace import project_identity


def main():
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='carryon-creation-regression-') as directory:
            root = Path(directory).resolve(); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) + '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            setup = AppServer(home, runtime_directory=root / 'setup')
            try:
                setup.connect()
                project = setup.rpc('project/create', {'idempotencyKey': 'fixture-project', 'name': 'fixture',
                                                       'roots': [{'path': str(root)}]})['project']
            finally: setup.close()
            (home / '.codex-global-state.json').write_text(json.dumps({'local-projects': {
                project['id']: {'name': 'fixture', 'rootPaths': [str(root)]}}}))
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
                body = {'requestId': 'fixture-create-request', 'projectId': project_identity(str(root), native_id=project['id'])[0],
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
                wait_until(lambda: tid not in manager.entries)
                rows = bridge.catalog.list(); assert len(rows) == 1, rows
                assert rows[0]['nativeProjectId'] == project['id'] and rows[0]['cwd'] == str(root)
                archiver = AppServer(home, runtime_directory=root / 'archiver')
                try:
                    archiver.connect()
                    archiver.rpc('thread/archive', {'threadId': tid})
                    assert bridge.catalog.list() == []
                finally: archiver.close()
                print(json.dumps({'passed': True, 'checks': ['create with zero existing conversations',
                    'native project identity', 'cloud request scoping', 'temporary runtime adoption',
                    'IPC owner task delivery', 'real streamed turn', 'duplicate request', 'automatic release',
                    'native archive after release']}))
            finally: bridge.shutdown(); journal.conn.close()
    finally: model.shutdown(); model.server_close()


if __name__ == '__main__': main()
