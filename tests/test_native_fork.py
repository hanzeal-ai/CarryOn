import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from carryon.app_server.app_server import AppServer
from carryon.desktop_ipc.ipc import IPCError
from carryon.errors import BridgeError
from carryon.sessions.bridge import Bridge
from carryon.sessions.forking import submit
from carryon.routes.remote_scope import scoped_dispatch, request_key
from carryon.store import Journal
from carryon.workspaces.workspace_access import capability, permissions

T = '11111111-1111-4111-8111-111111111111'
C = '22222222-2222-4222-8222-222222222222'


class NativeForkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name) / 'jobs.sqlite'); self.addCleanup(self.journal.conn.close)
        self.runtime = AppServer(self.temp.name); self.runtime.process = SimpleNamespace(poll=lambda: None)
        self.runtime.account_ready = True
        self.runtime._event({'method': 'thread/started', 'params': {'thread': {'id': T, 'cwd': self.temp.name,
            'status': {'type': 'idle'}, 'turns': [{'id': key, 'status': 'completed', 'items': []} for key in ('one', 'two')]}}})
        self.runtime.current(T)['threadMetadata'] = {'id': T, 'historyMode': 'paginated'}
        self.bridge = Bridge('unused', SimpleNamespace(get=lambda tid: {}), self.journal)
        self.bridge.ipc = self.runtime; self.bridge.enabled = True
        self.bridge.workspace = SimpleNamespace(catalog_refresh=Mock())
        self.notified = False
        self.bridge.notify = lambda: setattr(self, 'notified', True)
        self.calls = []; self.error = None; self.hook = lambda: None; self.closed = False
        outer = self
        class Creator:
            def __init__(self, *args, **kwargs): pass
            def connect(self): outer.hook()
            def require_account(self): pass
            def close(self): outer.closed = True
            def rpc(self, method, params, before_send):
                before_send(lambda: outer.calls.append((method, params)))
                if outer.error: raise outer.error
                return {'thread': {'id': C, 'forkedFromId': T, 'cwd': outer.temp.name,
                    'historyMode': 'paginated', 'status': {'type': 'idle'}}}
        self.patch = patch('carryon.sessions.forking.AppServer', Creator); self.patch.start(); self.addCleanup(self.patch.stop)

    def settled(self, key):
        for _ in range(200):
            job = self.journal.get(key)
            if job and job['state'] not in ('preparing', 'dispatching') and self.closed and self.notified: return job
            time.sleep(.01)
        self.fail('fork did not settle')

    def test_current_fork_has_exact_boundary_no_turn_and_deduplicates(self):
        data = {'requestId': 'fork-once'}
        submit(self.bridge, T, data); job = self.settled('fork-once')
        self.assertEqual((job['state'], job['threadId'], job['createdThreadId'], job['sourceThreadId']), ('completed', C, C, T))
        self.assertEqual(self.calls, [('thread/fork', {'threadId': T, 'lastTurnId': 'two', 'excludeTurns': True, 'deferGoalContinuation': True})])
        self.assertEqual(submit(self.bridge, T, data), job); self.assertEqual(len(self.calls), 1)
        self.bridge.workspace.catalog_refresh.assert_called_once()

    def test_selected_completed_turn_stays_exact(self):
        submit(self.bridge, T, {'requestId': 'fork-earlier', 'lastTurnId': 'one'})
        self.assertEqual(self.settled('fork-earlier')['state'], 'completed')
        self.assertEqual(self.calls[0][1]['lastTurnId'], 'one')

    def test_unknown_reply_never_reforks(self):
        self.error = IPCError('lost reply', uncertain=True)
        data = {'requestId': 'fork-unknown'}; submit(self.bridge, T, data)
        job = self.settled('fork-unknown'); self.assertEqual(job['state'], 'uncertain')
        self.assertEqual(submit(self.bridge, T, data), job); self.assertEqual(len(self.calls), 1)

    def test_revocation_or_new_turn_before_write_prevents_fork(self):
        self.hook = lambda: setattr(self.bridge, 'generation', self.bridge.generation + 1)
        submit(self.bridge, T, {'requestId': 'fork-revoked'})
        self.assertEqual(self.settled('fork-revoked')['state'], 'failed'); self.assertEqual(self.calls, [])
        self.closed = False
        self.notified = False
        self.hook = lambda: self.runtime._event({'method': 'turn/started', 'params': {'threadId': T,
            'turn': {'id': 'new', 'status': 'inProgress', 'items': []}}})
        submit(self.bridge, T, {'requestId': 'fork-stale'})
        self.assertEqual(self.settled('fork-stale')['state'], 'failed'); self.assertEqual(self.calls, [])

    def test_scope_permission_and_child_job_visibility(self):
        self.assertEqual(capability('POST', '/api/threads/' + T + '/fork'), 'create')
        with self.assertRaises(ValueError): permissions(['create'])
        path = '/api/threads/' + T + '/fork'; data = {'requestId': 'fork-scoped'}
        with self.assertRaises(BridgeError): scoped_dispatch(self.bridge, 'POST', path, data, False, 'binding')
        scoped_dispatch(self.bridge, 'POST', path, data, True, 'binding')
        job = self.settled(request_key('binding', 'fork-scoped'))
        status, result = scoped_dispatch(self.bridge, 'GET', '/api/jobs/fork-scoped', None, True, 'binding')
        self.assertEqual((status, result['id'], result['createdThreadId']), (200, 'fork-scoped', C))
        self.assertEqual(job['sourceThreadId'], T)
        with self.assertRaises(BridgeError): scoped_dispatch(self.bridge, 'GET', '/api/jobs/fork-scoped', None, True, 'other')
