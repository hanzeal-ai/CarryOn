"""Owner IPC -> real app-server -> local model fixture, with an isolated CODEX_HOME."""
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
from carryon.owner.manager import OwnerManager
from carryon.owner.integration import OwnerBridge
from carryon.store import Journal
from carryon.routes.remote_scope import scoped_dispatch


def main():
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='carryon-owner-regression-') as directory:
            root = Path(directory).resolve(); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) + '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            initial = AppServer(home, runtime_directory=root / 'initial')
            try:
                initial.connect()
                tid = initial.rpc('thread/start', {'cwd': str(root), 'historyMode': 'paginated'})['thread']['id']
                initial.start(tid, 'fixture seed', 'app-server', 'seed-input', lambda write: write())
                wait_until(lambda: any(t['status'] == 'completed' for t in initial.current(tid)['turns']))
                wait_until(lambda: bool(Catalog(home).list()))
            finally: initial.close()
            # A socketpair supplies the router's already-initialized peer connection.
            # Framing, owner handlers, follower snapshots and app-server are production code.
            class Follower(DesktopIPC):
                def owner(self, thread_id, **kwargs):
                    # The socketpair has no router; emulate only its missing-client reply.
                    if thread_id not in manager.entries: raise IPCError('no-client-found')
                    return super().owner(thread_id, **kwargs)
            follower = Follower('unused'); follower.client_id = 'fixture-desktop'
            class OwnerTransport(DesktopIPC):
                def connect(self):
                    self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                    for ipc in (self, follower):
                        threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
                def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
            manager = OwnerManager(home, root / 'owner', Catalog(home), transport_factory=OwnerTransport)
            journal = Journal(root / 'jobs.sqlite')
            bridge = OwnerBridge('unused', manager.catalog, journal, owner_directory=root / 'owner')
            bridge.ipc = follower; bridge.enabled = True; bridge.owner_service = manager
            manager.bus.connect()
            try:
                observed = {}
                def observe():
                    current = follower.current(tid)
                    if current is not None: observed['state'] = current
                follower.on_change = observe
                path = '/api/threads/' + tid + '/compose'
                for index in range(2):
                    if index:
                        # Reconnect the socketpair after release; the real desktop router
                        # keeps the bridge connection alive independently of owner peers.
                        wait_until(lambda: not follower.connected)
                        manager.bus.connect()
                    assert tid not in manager.entries
                    body = {'requestId': 'owner-followup-' + str(index), 'prompt': 'fixture follow-up'}
                    status, job = scoped_dispatch(bridge, 'POST', path, body, True, 'fixture-binding')
                    assert status == 202 and job['state'] == 'accepted', job
                    turn_id = job['turnId']
                    native_duplicate = follower.start(tid, body['prompt'], 'fixture-owner',
                                                      job['clientMessageId'], lambda write: write())
                    assert native_duplicate['id'] == turn_id
                    duplicate = scoped_dispatch(bridge, 'POST', path, body, True, 'fixture-binding')[1]
                    assert duplicate['turnId'] == turn_id
                    wait_until(lambda: any(t['turnId'] == turn_id and t['status'] == 'completed'
                                           for t in observed.get('state', {}).get('turns', [])))
                    state = observed['state']
                    assert state['executionBackend'] == 'carryon-owner'
                    turn = next(t for t in state['turns'] if t['turnId'] == turn_id)
                    assert any(i.get('text') == 'fixture response' for i in turn['items'])
                    assert len(state['turns']) == 2 + index
                    wait_until(lambda: tid not in manager.entries)
                # A different real app-server must now archive without active-writer rejection.
                archiver = AppServer(home, runtime_directory=root / 'archiver')
                try:
                    archiver.connect()
                    archiver.rpc('thread/archive', {'threadId': tid})
                    with Catalog(home).connection() as db:
                        assert db.execute('SELECT archived FROM threads WHERE id=?', (tid,)).fetchone()[0] == 1
                finally: archiver.close()
                print(json.dumps({'passed': True, 'checks': ['isolated paginated resume', 'IPC owner discovery',
                    'canonical history', 'real turn/start', 'streamed completion', 'idempotent start', 'idempotent compose', 'unloaded compose auto-load', 'send after automatic release',
                    'automatic owner release', 'archive from another app-server']}))
            finally: follower.close(); bridge.shutdown(); journal.conn.close()
    finally: model.shutdown(); model.server_close()


if __name__ == '__main__': main()
