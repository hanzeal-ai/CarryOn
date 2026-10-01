"""Owner IPC -> real app-server -> local model fixture, with an isolated CODEX_HOME."""
import json
import socket
import sys
import tempfile
import threading
import time
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
from carryon.routes.remote_scope import scoped_dispatch, request_key


def main():
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='carryon-owner-regression-') as directory:
            root = Path(directory).resolve(); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(model.server_port) + '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            initial = AppServer(home, runtime_directory=root / 'initial')
            try:
                started = time.perf_counter()
                initial.connect()
                cold_initialize_ms = (time.perf_counter() - started) * 1000
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
                with manager.prewarm.condition:
                    assert manager.prewarm.condition.wait_for(lambda: manager.prewarm.worker is None, timeout=10)
                assert manager.prewarm.runtime.rpc('thread/loaded/list', {})['data'] == []
                started = time.perf_counter()
                unused = manager.prewarm.take()
                warm_acquire_ms = (time.perf_counter() - started) * 1000
                unused.close()
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
                    with manager.prewarm.condition:
                        assert manager.prewarm.condition.wait_for(lambda: manager.prewarm.worker is None, timeout=10)
                        prepared = manager.prewarm.runtime
                    assert prepared.rpc('thread/loaded/list', {})['data'] == []
                    body = {'requestId': 'owner-followup-' + str(index), 'prompt': 'fixture follow-up'}
                    status, job = scoped_dispatch(bridge, 'POST', path, body, True, 'fixture-binding')
                    assert status == 202, job
                    key = request_key('fixture-binding', body['requestId'])
                    wait_until(lambda: journal.get(key)['state'] not in ('preparing', 'dispatching'))
                    job = scoped_dispatch(bridge, 'GET', '/api/jobs/' + body['requestId'], None, True, 'fixture-binding')[1]
                    assert job['state'] == 'accepted', job
                    assert manager.entries[tid]['runtime'] is prepared
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
                    assert len(state['turns']) == 2 + index * 2
                    # The desktop still follows the owner after the mobile turn.
                    # A later native request must reach that same owner successfully.
                    manager._release_finished()
                    assert tid in manager.entries
                    wait_until(lambda: manager.entries[tid].get('suspended'))
                    assert not manager.entries[tid]['runtime'].connected
                    # Even while the desktop is subscribed, an independent native
                    # process can archive. Restore the fixture for the next send.
                    archiver = AppServer(home, runtime_directory=root / ('between-turns-' + str(index)))
                    try:
                        archiver.connect()
                        archiver.rpc('thread/archive', {'threadId': tid})
                        archiver.rpc('thread/unarchive', {'threadId': tid})
                    finally: archiver.close()
                    with manager.prewarm.condition:
                        assert manager.prewarm.condition.wait_for(lambda: manager.prewarm.worker is None, timeout=10)
                        prepared_resume = manager.prewarm.runtime
                    assert prepared_resume.rpc('thread/loaded/list', {})['data'] == []
                    desktop_turn = follower.start(tid, 'desktop append', 'fixture-owner',
                        'desktop-append-' + str(index), lambda write: write())['id']
                    assert manager.entries[tid]['runtime'] is prepared_resume
                    wait_until(lambda: any(t['turnId'] == desktop_turn and t['status'] == 'completed'
                                           for t in observed.get('state', {}).get('turns', [])))
                    follower._write({'type': 'broadcast', 'method': 'thread-stream-following-changed',
                        'version': 1, 'sourceClientId': follower.client_id, 'targetClientIds': ['fixture-owner'],
                        'params': {'hostId': 'local', 'conversationId': tid, 'following': False}})
                    wait_until(lambda: tid not in manager.entries)
                # A different real app-server must now archive without active-writer rejection.
                archiver = AppServer(home, runtime_directory=root / 'archiver')
                try:
                    archiver.connect()
                    archiver.rpc('thread/archive', {'threadId': tid})
                    with Catalog(home).connection() as db:
                        assert db.execute('SELECT archived FROM threads WHERE id=?', (tid,)).fetchone()[0] == 1
                finally: archiver.close()
                print(json.dumps({'passed': True, 'coldInitializeMs': round(cold_initialize_ms, 3),
                    'warmAcquireMs': round(warm_acquire_ms, 3), 'checks': ['initialized unused spare', 'same prewarmed process assigned', 'refill after acquisition', 'prewarmed suspended-owner resume',
                    'isolated paginated resume', 'IPC owner discovery',
                    'canonical history', 'real turn/start', 'streamed completion', 'idempotent start', 'idempotent compose', 'unloaded compose auto-load', 'send after automatic release',
                    'desktop append after mobile completion', 'archive while still subscribed',
                    'owner release after unfollow', 'archive from another app-server']}))
            finally: follower.close(); bridge.shutdown(); journal.conn.close()
    finally: model.shutdown(); model.server_close()


if __name__ == '__main__': main()
