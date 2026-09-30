import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from carryon.workspaces.workspaces import create, initialize
from carryon.services import records, remove
from carryon.app_server.app_server import AppServer


class WorkspaceIsolationTests(unittest.TestCase):
    def started(self, server, thread):
        # Exercise the actual notification adapter, including request handling.
        thread = {'cwd': '/tmp', 'status': {'type': 'notLoaded'}, **thread}
        server._event({'method': 'thread/started', 'params': {'thread': thread}})
        return server.snapshots[thread['id']]

    def test_native_user_messages_keep_identity_order_and_control_input(self):
        from carryon.sessions.bridge import snapshot_history
        messages = [
            {'id': 'u1', 'clientId': 'sent-1', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'first'}]},
            {'id': 'a', 'type': 'agentMessage', 'text': 'reply'},
            {'id': 'u2', 'clientId': 'sent-2', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'second'}]},
        ]
        state = self.started(AppServer('/tmp'), {'id': 't', 'turns': [{'id': 'turn', 'status': 'completed', 'items': messages}]})
        history = snapshot_history(state)
        rows = history['timeline'][1:]
        self.assertEqual(state['turns'][0]['items'], messages)
        self.assertEqual([r['nativeId'] for r in rows], ['u1', 'a', 'u2'])
        self.assertEqual([r['text'] for r in rows], ['first', 'reply', 'second'])
        self.assertEqual([r['clientMessageId'] for r in rows], ['sent-1', None, 'sent-2'])
        self.assertEqual(history['controls']['lastUserText'], 'second')

    def test_streamed_user_messages_replace_by_native_id_and_survive_completion(self):
        from carryon.sessions.bridge import snapshot_history
        with tempfile.TemporaryDirectory() as temp:
            server = AppServer(Path(temp))
            self.started(server, {'id': 't', 'turns': [{'id': 'turn', 'status': 'inProgress', 'items': []}]})
            for identifier, text in [('u1', 'first'), ('a', 'reply'), ('u2', 'second')]:
                item = {'id': identifier, 'type': 'agentMessage', 'text': text} if identifier == 'a' else {
                    'id': identifier, 'type': 'userMessage', 'clientId': identifier + '-client', 'content': [{'type': 'text', 'text': text}]}
                for method in ('item/started', 'item/completed'):
                    server._apply({'method': method, 'params': {'turnId': 'turn', 'item': item}}, 't')
            before = server.snapshots['t']
            server._apply({'method': 'turn/completed', 'params': {'turn': {'id': 'turn', 'status': 'completed', 'items': []}}}, 't')
            history = snapshot_history(server.snapshots['t'])
            self.assertEqual([r['nativeId'] for r in history['timeline'][1:]], ['u1', 'a', 'u2'])
            self.assertEqual(history['controls']['lastUserText'], 'second')
            self.assertEqual(before['turns'][0]['status'], 'inProgress')
            server._apply({'method': 'turn/completed', 'params': {'turn': {
                'id': 'turn', 'status': 'completed', 'itemsView': 'summary',
                'items': [{'id': 'a', 'type': 'agentMessage', 'text': 'final reply'}]}}}, 't')
            history = snapshot_history(server.snapshots['t'])
            self.assertEqual([r['nativeId'] for r in history['timeline'][1:]], ['u1', 'a', 'u2'])
            self.assertEqual(history['timeline'][2]['text'], 'final reply')
            self.assertEqual(history['controls']['lastUserText'], 'second')
            server._apply({'method': 'turn/completed', 'params': {'turn': {
                'id': 'turn', 'status': 'completed', 'itemsView': 'full',
                'items': [{'id': 'a', 'type': 'agentMessage', 'text': 'authoritative'}]}}}, 't')
            self.assertEqual([i['id'] for i in server.snapshots['t']['turns'][0]['items']], ['a'])

    @patch("carryon.usage.executable", return_value="codex")
    def test_one_ipc_and_independent_new_workspaces(self, _executable):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with patch.dict(os.environ, {'CARRYON_REGISTRY_DIR':str(root/'registry'), 'CODEX_HOME':str(root/'actual-codex')}):
                first = initialize(root/'default')
                self.assertEqual(first['codexHome'], str(root/'actual-codex'))
                self.assertEqual(initialize(root/'default'), first)
                with self.assertRaisesRegex(ValueError,'已有'): initialize(root/'another-ipc')
                a, b = create('A'), create('B')
                self.assertNotEqual(a['codexHome'], b['codexHome'])
                self.assertNotEqual(a['codexHome'], first['codexHome'])
                self.assertFalse((Path(a['codexHome'])/'auth.json').exists())
                marker = Path(a['codexHome'])/'session'; marker.write_text('keep')
                remove(a['directory'])
                with self.assertRaisesRegex(ValueError, '已删除'):
                    initialize(a['directory'])
                self.assertTrue(records()[a['directory']]['removed'])
                self.assertEqual(marker.read_text(),'keep')
                self.assertFalse(records()[b['directory']]['removed'])

    def test_projection_preserves_native_turn_and_approval(self):
        request = {'id':3, 'method':'item/commandExecution/requestApproval','params':{'threadId':'a'}}
        server = AppServer('/tmp')
        self.started(server, {'id':'a','cwd':'/tmp','status':{'type':'active'},'turns':[{'id':'turn','status':'inProgress',
            'items':[{'id':'user','type':'userMessage','content':[{'type':'text','text':'hello'}]},
                     {'id':'agent','type':'agentMessage','text':'response'}]}]})
        server._event(request)
        state = server.snapshots['a']
        self.assertEqual(state['turns'][0]['items'][0]['content'][0]['text'],'hello')
        self.assertNotIn('params', state['turns'][0])
        self.assertEqual(state['requests'][0],request)
        self.assertEqual(state['threadRuntimeStatus']['type'],'active')

    def test_real_app_server_isolation_without_model_execution(self):
        from carryon.usage import executable
        from carryon.errors import BridgeError
        try:
            executable()
        except BridgeError:
            self.skipTest('Native integration requires an installed Codex executable')
        with tempfile.TemporaryDirectory() as temp:
            a, b = AppServer(Path(temp)/'a'), AppServer(Path(temp)/'b')
            a.home.mkdir(); b.home.mkdir()
            try:
                a.connect(); b.connect()
                self.assertIsNone(a.rpc('account/read', {'refreshToken':False})['account'])
                thread = a.rpc('thread/start', {'cwd':str(a.home),'approvalPolicy':'on-request','sandbox':'workspace-write'})['thread']
                self.assertTrue(Path(thread['path']).is_relative_to(a.home))
                self.assertEqual(a.rpc('thread/read',{'threadId':thread['id'],'includeTurns':False})['thread']['id'],thread['id'])
                self.assertNotIn(thread['id'],[t['id'] for t in b.rpc('thread/list',{'limit':100})['data']])
                from carryon.desktop_ipc.ipc import IPCError
                with self.assertRaises(IPCError): b.rpc('thread/read',{'threadId':thread['id'],'includeTurns':False})
            finally: a.close(); b.close()

class AppServerDeliveryTests(unittest.TestCase):
    def test_direct_creation_tracks_native_terminal_status_and_retries_do_not_create(self):
        from carryon.app_server.app_server_bridge import AppServerBridge
        from carryon.store import Journal
        from unittest.mock import Mock
        for terminal in ('failed','interrupted','completed'):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as temp:
                journal=Journal(Path(temp)/'jobs.sqlite'); bridge=AppServerBridge(Path(temp),journal); bridge.workspace_directory=Path(temp)
                ipc=Mock();ipc.authenticated=True;ipc.connected=True;ipc.lock=__import__('threading').RLock();ipc.threads={}
                tid='11111111-1111-1111-1111-111111111111'
                ipc.rpc.return_value={'thread':{'id':tid}}
                ipc.start.return_value={'id':'turn','status':'inProgress'}
                bridge.enabled=True;bridge.ipc=ipc;bridge.workspace=Mock()
                job={'id':'create-test','kind':'create','threadId':'','state':'preparing','created':1,'fingerprint':'hash','clientMessageId':'msg'}
                journal.insert(job)
                from carryon.app_server.app_creation import dispatch
                dispatch(bridge,ipc,0,job,'hello',None)
                self.assertEqual(journal.get(job['id'])['state'],'accepted')
                with patch.object(bridge,'turn_evidence',return_value={'status':terminal}):
                    self.assertEqual(bridge._refresh_job(job['id'])['state'],terminal)
                self.assertEqual(ipc.rpc.call_count,1)
                self.assertEqual(journal.get(job['id'])['createdThreadId'],tid)
                journal.conn.close()

class AppServerResponseReceiptTests(unittest.TestCase):
    def setUp(self):
        import threading
        from carryon.app_server.app_server_bridge import AppServerBridge
        from carryon.store import Journal
        from unittest.mock import Mock
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = AppServer(Path(self.temp.name))
        self.server.process = Mock()
        self.server.process.poll.return_value = None
        self.journal = Journal(Path(self.temp.name) / 'jobs.sqlite')
        self.addCleanup(self.journal.conn.close)
        self.bridge = AppServerBridge(Path(self.temp.name), self.journal)
        self.bridge.enabled = True
        self.bridge.ipc = self.server
        self.bridge.assert_target = lambda *args: None
        self.tid = '11111111-1111-4111-8111-111111111111'
        self.request = {'id': 17, 'method':'item/commandExecution/requestApproval', 'params':{'threadId':self.tid}}
        self.state = {'id':self.tid, 'turns':[], 'requests':[self.request], 'threadRuntimeStatus':{'type':'active'}}
        self.server.snapshots[self.tid] = self.state
        self.server.snapshot = lambda tid: ('app-server', self.server.current(tid))
        self.writes = []
        self.server._write = self.writes.append
        original = self.server.request
        self.server.request = lambda *args: original(*args, timeout_ms=10)

    def submit(self, rid='reply-test'):
        from carryon.sessions.operations import submit
        from carryon.contracts import digest
        return submit(self.bridge, self.tid, {'action':'command-approval','requestId':rid,
            'nativeRequestId':17,'requestFingerprint':digest(self.request),'decision':'decline'})

    def resolve(self, tid=None, request_id=17):
        self.server._event({'method':'serverRequest/resolved','params':{'threadId':tid or self.tid,'requestId':request_id}})

    def test_write_without_resolution_stays_uncertain_and_does_not_replay(self):
        self.assertEqual(self.submit()['state'], 'uncertain')
        self.assertEqual(self.submit()['state'], 'uncertain')
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.submit('another-reply')['state'], 'failed')
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(len(self.server.current(self.tid)['requests']), 1)

    def test_exact_resolution_confirms_reply_and_late_resolution_recovers(self):
        self.assertEqual(self.submit()['state'], 'uncertain')
        self.resolve('22222222-2222-4222-8222-222222222222')
        self.resolve(request_id='17')
        self.assertEqual(self.bridge._refresh_job('reply-test')['state'], 'uncertain')
        self.resolve()
        result = self.bridge._refresh_job('reply-test')
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['evidence'], 'native-server-request-resolved')
        self.assertEqual(self.writes, [{'id':17,'result':{'decision':'decline'}}])
        self.assertEqual(self.server.response_waiters, {})

    def test_resolution_during_write_is_not_lost(self):
        def write(value):
            self.writes.append(value)
            self.resolve()
        self.server._write = write
        result = self.submit()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['evidence'], 'native-server-request-resolved')
        self.assertEqual(self.server.response_waiters, {})

    def test_disconnect_and_new_process_cannot_confirm_old_reply(self):
        def write(value):
            self.writes.append(value)
            self.server.process = None
            self.server.close()
        self.server._write = write
        self.assertEqual(self.submit()['state'], 'uncertain')
        self.assertEqual(self.server.response_waiters, {})
        from unittest.mock import Mock
        self.server.process = Mock(); self.server.process.poll.return_value = None
        self.server.session_id = 'new-process'
        self.server.response_resolved = lambda *args: True
        self.assertEqual(self.bridge._refresh_job('reply-test')['state'], 'uncertain')

    def test_cancel_before_write_is_known_failure_and_releases_waiter(self):
        from carryon.desktop_ipc.ipc import IPCError
        def cancel(write): raise IPCError('authorization revoked')
        with self.assertRaises(IPCError) as raised:
            self.server.respond(self.tid, {'requestId':17,'decision':'decline'}, cancel, 10)
        self.assertFalse(raised.exception.uncertain)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.server.response_waiters, {})

    def test_known_transport_refusal_releases_unsent_waiter(self):
        from carryon.desktop_ipc.ipc import IPCError
        def refuse(value): raise IPCError('disconnected')
        self.server._write = refuse
        self.assertEqual(self.submit()['state'], 'failed')
        self.assertEqual(self.server.response_waiters, {})

    def test_partial_write_error_retains_uncertain_receipt(self):
        def partial(value): raise OSError('broken pipe')
        self.server._write = partial
        self.assertEqual(self.submit()['state'], 'uncertain')
        self.assertEqual(len(self.server.response_waiters), 1)
