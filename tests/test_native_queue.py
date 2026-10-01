import tempfile
import unittest
from types import SimpleNamespace
from carryon.app_server.app_server import AppServer, thread_settings
from carryon.contracts import digest
from carryon.desktop_ipc.ipc import IPCError


class QueueDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.runtime = AppServer(self.temp.name)
        self.runtime.process = SimpleNamespace(poll=lambda: None)
        self.runtime.account_ready = True
        self.runtime._event({'method': 'thread/started', 'params': {'thread': {
            'id': 't', 'cwd': self.temp.name, 'status': {'type': 'idle'}, 'turns': []}}})
        self.rows = [{'id': 'native-id', 'clientUserMessageId': 'client-id', 'input': [{'type': 'text', 'text': 'task'}]}]
        self.calls = []
        self.runtime.rpc = self.rpc

    def rpc(self, method, params, before_send=None, **kwargs):
        if method == 'thread/queue/list': return {'data': self.rows, 'nextCursor': None}
        write = lambda: self.calls.append((method, params))
        if before_send: before_send(write)
        else: write()
        if method == 'thread/queue/start':
            self.rows = []
            return {'turn': {'id': 'started-turn', 'status': 'inProgress', 'items': []}}
        return {}

    def test_idle_queue_resumes_through_native_start(self):
        from carryon.app_server.queue import replace
        rows = self.runtime.queue_snapshot('t', refresh=True)
        resumed = [{k: v for k, v in rows[0].items() if k != 'pausedReason'}]
        replace(self.runtime, 't', resumed, digest(rows), lambda write: write())
        self.assertEqual(self.calls, [('thread/queue/start', {'threadId': 't', 'queuedSubmissionId': 'native-id'})])
        self.assertEqual(self.runtime.current('t')['threadRuntimeStatus']['type'], 'active')

    def test_direct_start_and_resume_share_execution_lock_and_seed_active_state(self):
        original = self.rpc
        def rpc(method, params, before_send=None):
            if method != 'turn/start': return original(method, params, before_send)
            before_send(lambda: self.calls.append((method, params)))
            return {'turn': {'id': 'direct', 'status': 'inProgress', 'items': []}}
        self.runtime.rpc = rpc
        self.runtime.start_turn('t', {'threadId': 't', 'input': []})
        with self.assertRaises(IPCError): self.runtime.start_turn('t', {'threadId': 't', 'input': []})
        self.assertEqual(len(self.calls), 1)

    def test_completion_before_start_reply_is_not_overwritten(self):
        def rpc(method, params, before_send=None):
            before_send(lambda: None)
            turn = {'id': 'fast', 'status': 'completed', 'items': []}
            self.runtime._event({'method': 'turn/completed', 'params': {'threadId': 't', 'turn': turn}})
            return {'turn': {**turn, 'status': 'inProgress'}}
        self.runtime.rpc = rpc
        self.runtime.start_turn('t', {'threadId': 't', 'input': []})
        self.assertEqual(self.runtime.current('t')['turns'][0]['status'], 'completed')


class NativeProjectionTests(unittest.TestCase):
    def test_settings_keep_native_fields_and_normalize_effort(self):
        self.assertEqual(thread_settings({'model': 'test', 'reasoningEffort': 'high', 'cwd': '/tmp', 'serviceTier': 'fast'}),
            {'model': 'test', 'effort': 'high', 'cwd': '/tmp', 'serviceTier': 'fast'})

    def test_initial_sandbox_and_permission_profile_are_preserved(self):
        self.assertEqual(thread_settings({'sandbox': {'type': 'workspaceWrite'}, 'activePermissionProfile': 'default'}),
                         {'sandboxPolicy': {'type': 'workspaceWrite'}, 'activePermissionProfile': 'default', 'effort': None})

    def test_diff_is_immutable_isolated_and_survives_completion_summary(self):
        runtime = AppServer('/tmp')
        for tid in ('a', 'b'):
            runtime._event({'method': 'thread/started', 'params': {'thread': {'id': tid, 'cwd': '/tmp',
                'status': {'type': 'active'}, 'turns': [{'id': 'turn', 'status': 'inProgress', 'items': []}]}}})
        before = runtime.current('a')
        runtime._event({'method': 'turn/diff/updated', 'params': {'threadId': 'a', 'turnId': 'turn', 'diff': '+test'}})
        runtime._event({'method': 'turn/completed', 'params': {'threadId': 'a', 'turn': {'id': 'turn', 'status': 'completed', 'items': []}}})
        self.assertNotIn('diff', before['turns'][0])
        self.assertNotIn('diff', runtime.current('b')['turns'][0])
        self.assertEqual(runtime.current('a')['turns'][0]['diff'], '+test')
