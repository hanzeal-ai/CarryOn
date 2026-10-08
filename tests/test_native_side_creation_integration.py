"""Native ephemeral lifetime and model-context isolation, never real accounts."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from run_appserver_regression import Model, wait_until
from carryon.app_server.app_server import AppServer
from carryon.app_server.app_server_bridge import AppServerBridge
from carryon.desktop_ipc.ipc import IPCError
from carryon.routes.api import dispatch
from carryon.sessions.side_creation import BOUNDARY
from carryon.store import Journal


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeSideCreationIntegration(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests
        class Capture(Model):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                requests.append(json.loads(raw))
                original = self.rfile
                try:
                    self.rfile = io.BytesIO(raw)
                    super().do_POST()
                finally: self.rfile = original
        self.model = ThreadingHTTPServer(('127.0.0.1', 0), Capture)
        threading.Thread(target=self.model.serve_forever, daemon=True).start()
        self.temp = tempfile.TemporaryDirectory(prefix='carryon-native-side-')
        root = Path(self.temp.name); home = root / 'home'; home.mkdir()
        (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
            '[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' + str(self.model.server_port) +
            '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
        self.journal = Journal(root / 'jobs.sqlite')
        self.bridge = AppServerBridge(home, self.journal); self.bridge.enable()
        self.runtime = self.bridge.ipc
        self.parent = self.runtime.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda w: w())['id']
        self.runtime.start(self.parent, 'PARENT REFERENCE ONLY', 'app-server', 'fixture-parent', lambda w: w())
        wait_until(lambda: self.runtime.queue_idle(self.runtime.current(self.parent)))
        self.runtime.rpc('thread/goal/set', {'threadId': self.parent, 'objective': 'PARENT GOAL', 'status': 'paused'})

    def tearDown(self):
        if hasattr(self.bridge, "shutdown"): self.bridge.shutdown()
        else: self.bridge.disable()
        self.journal.conn.close()
        self.model.shutdown(); self.model.server_close(); self.temp.cleanup()

    def create(self, key='fixture-side-create', authorize=None):
        status, job = dispatch(self.bridge, 'POST', '/api/threads/' + self.parent + '/side-chats',
                              {'requestId': key}, authorize=authorize)
        self.assertEqual(status, 202)
        wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
        return self.journal.get(key)

    def test_create_send_isolation_unknown_receipt_and_close(self):
        before = len(self.requests)
        job = self.create(); self.assertEqual(job['state'], 'completed', job)
        child = job['createdThreadId']; endpoint = self.bridge.native_sides[child]
        self.assertEqual(len(self.requests), before)
        self.assertEqual(self.create(), job)
        history = self.bridge.side_history(self.parent, child)
        self.assertEqual(history['timeline'], [])
        self.assertFalse(history['controls']['supportsGoal'])
        self.assertFalse(history['controls']['supportsMentions'])
        self.assertFalse(history['queue']['supported'])
        self.assertEqual(self.bridge.side_chats(self.parent)['chats'][0]['id'], child)
        path = '/api/side-chats/' + child
        body = {'parentId': self.parent, 'requestId': 'fixture-side-question', 'prompt': 'SIDE QUESTION'}
        _, sent = dispatch(self.bridge, 'POST', path + '/compose', body)
        self.assertEqual(sent['state'], 'accepted', sent)
        wait_until(lambda: endpoint.ipc.queue_idle(endpoint.ipc.current(child)))
        self.assertEqual(len(self.requests), before + 1)
        context = json.dumps(self.requests[-1])
        self.assertIn('PARENT REFERENCE ONLY', context)
        self.assertIn('Side conversation boundary.', context)
        self.assertIn('SIDE QUESTION', context)
        self.assertEqual(len(self.runtime.current(self.parent)['turns']), 1)
        self.assertEqual(len(endpoint.ipc.current(child)['turns']), 1)
        self.assertFalse(any(t['id'] == child for t in self.runtime.rpc('thread/list', {'limit': 100})['data']))
        # Unknown delivery is reconciled only from the live native message ID.
        self.journal.update(sent['id'], state='uncertain')
        self.assertEqual(self.bridge.refresh_job(sent['id'])['state'], 'accepted')
        self.assertEqual(len(self.requests), before + 1)
        with self.assertRaises(ValueError): self.bridge.side_history('11111111-1111-4111-8111-111111111111', child)
        close = {'parentId': self.parent, 'requestId': 'fixture-side-close'}
        _, closed = dispatch(self.bridge, 'POST', path + '/close', close)
        self.assertEqual(closed['state'], 'completed')
        self.assertFalse(endpoint.ipc.connected)
        self.assertNotIn(child, self.bridge.native_sides)
        self.assertEqual(dispatch(self.bridge, 'POST', path + '/close', close)[1], closed)
        self.assertEqual(self.create(), job)  # Never recreate a lost ephemeral identity.

    def test_boundary_unknown_never_publishes_or_replays(self):
        original = AppServer.rpc
        def rpc(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/inject_items': raise IPCError('fixture lost response', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', rpc): job = self.create()
        self.assertEqual(job['state'], 'uncertain', job)
        self.assertEqual(self.bridge.native_sides, {})
        self.assertEqual(self.create(), job)
        self.assertEqual(len(self.requests), 1)

    def test_revocation_before_boundary_and_disable(self):
        def authorize():
            job = self.journal.get('fixture-revoked')
            if job and job.get('createdThreadId'): raise PermissionError('fixture revoked')
        job = self.create('fixture-revoked', authorize)
        self.assertEqual(job['state'], 'uncertain', job)
        self.assertEqual(self.bridge.native_sides, {})
        good = self.create('fixture-valid'); self.assertEqual(good['state'], 'completed', good)
        endpoint = self.bridge.native_sides[good['createdThreadId']]
        self.bridge.disable()
        self.assertFalse(endpoint.ipc.connected)
        self.assertEqual(self.bridge.native_sides, {})

    def test_unloaded_parent_never_resumes(self):
        self.runtime.snapshots.pop(self.parent)
        original = self.runtime.rpc
        methods = []
        def rpc(method, *args, **kwargs):
            methods.append(method)
            return original(method, *args, **kwargs)
        with patch.object(self.runtime, 'rpc', rpc): job = self.create()
        self.assertEqual(job['state'], 'failed', job)
        self.assertNotIn('thread/resume', methods)
        self.assertNotIn('thread/fork', methods)
        self.assertEqual(len(self.requests), 1)

    def test_parent_reconnect_closes_old_children(self):
        job = self.create(); self.assertEqual(job['state'], 'completed', job)
        endpoint = self.bridge.native_sides[job['createdThreadId']]
        self.runtime.close()
        self.bridge.enable()
        self.assertEqual(self.bridge.native_sides, {})
        self.assertFalse(endpoint.ipc.connected)
        with self.assertRaises(Exception): endpoint.require()

    def test_parent_session_changes_after_boundary_never_publishes(self):
        original = AppServer.rpc
        def rpc(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/inject_items': self.runtime.session_id = 'new-session'
            return result
        with patch.object(AppServer, 'rpc', rpc): job = self.create()
        self.assertEqual(job['state'], 'uncertain', job)
        self.assertEqual(self.bridge.native_sides, {})

    def test_dead_child_remains_visible_and_can_be_closed(self):
        job = self.create(); child = job['createdThreadId']
        endpoint = self.bridge.native_sides[child]; endpoint.ipc.close()
        self.assertEqual(self.bridge.side_chats(self.parent)['chats'][0]['id'], child)
        _, closed = dispatch(self.bridge, 'POST', '/api/side-chats/' + child + '/close',
                             {'parentId': self.parent, 'requestId': 'fixture-dead-close'})
        self.assertEqual(closed['state'], 'completed')
        self.assertEqual(self.bridge.native_sides, {})

    def owner_fixture(self):
        import socket
        from carryon.desktop_ipc.ipc import DesktopIPC
        from carryon.owner.manager import OwnerManager
        from carryon.owner.integration import OwnerBridge
        from carryon.sessions.catalog import Catalog
        self.runtime.close()
        follower = DesktopIPC('unused'); follower.client_id = 'fixture-follower'
        class Transport(DesktopIPC):
            def connect(self):
                self.sock, follower.sock = socket.socketpair(); self.client_id = 'fixture-owner'
                for ipc in (self, follower):
                    threading.Thread(target=ipc._reader, args=(ipc.sock,), daemon=True).start()
            def owner(self, *_args, **_kwargs): raise IPCError('no-client-found')
        root = Path(self.temp.name); home = root / 'home'
        catalog = Catalog(home)
        manager = OwnerManager(home, root / 'owner', catalog, transport_factory=Transport)
        self.bridge = OwnerBridge('unused', catalog, self.journal, owner_directory=root / 'owner')
        self.bridge.ipc = follower; self.bridge.enabled = True; self.bridge.owner_service = manager
        manager.load(self.parent)
        self.runtime = manager.entries[self.parent]['runtime']
        follower.snapshot(self.parent)
        return manager

    def test_owner_parent_release_does_not_terminate_side(self):
        manager = self.owner_fixture()
        job = self.create(); self.assertEqual(job['state'], 'completed', job)
        child = job['createdThreadId']; endpoint = self.bridge.native_sides[child]
        # A real coordinator keeps the follower connected when an Owner exits.
        # Our socketpair has no separate router, so keep that fixture link alive.
        with patch.object(manager.bus, "close", lambda: None): manager.release(self.parent)
        self.assertFalse(self.runtime.connected)
        self.assertTrue(endpoint.ipc.connected)
        _, sent = dispatch(self.bridge, 'POST', '/api/side-chats/' + child + '/compose',
            {'parentId': self.parent, 'requestId': 'fixture-owner-side-send', 'prompt': 'owner side question'})
        self.assertEqual(sent['state'], 'accepted', sent)
        wait_until(lambda: endpoint.ipc.queue_idle(endpoint.ipc.current(child)))
        self.journal.update(sent['id'], state='uncertain')
        self.assertEqual(self.bridge.refresh_job(sent['id'])['state'], 'accepted')
        self.assertNotIn(self.parent, manager.entries)
        _, closed = dispatch(self.bridge, 'POST', '/api/side-chats/' + child + '/close',
            {'parentId': self.parent, 'requestId': 'fixture-owner-close'})
        self.assertEqual(closed['state'], 'completed')

    def test_owner_conflict_after_boundary_never_publishes(self):
        manager = self.owner_fixture()
        original = AppServer.rpc
        def rpc(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/inject_items':
                with manager.lock: manager.entries[self.parent]['conflict'] = True
            return result
        with patch.object(AppServer, 'rpc', rpc): job = self.create()
        self.assertEqual(job['state'], 'uncertain', job)
        self.assertEqual(self.bridge.native_sides, {})
