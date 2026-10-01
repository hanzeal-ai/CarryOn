import copy
import tempfile
import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from carryon.app_server.app_server import AppServer
from carryon.app_server.review import request
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.bridge import Bridge
from carryon.sessions.operations import submit, controls, build
from carryon.store import Journal
from carryon.workspaces.workspace_access import capability

T = '11111111-1111-4111-8111-111111111111'


class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.runtime = AppServer(self.temp.name); self.runtime.process = SimpleNamespace(poll=lambda: None)
        self.runtime.account_ready = True
        self.runtime._event({'method': 'thread/started', 'params': {'thread': {
            'id': T, 'cwd': self.temp.name, 'status': {'type': 'idle'}, 'turns': []}}})
        self.journal = Journal(Path(self.temp.name) / 'jobs.sqlite'); self.addCleanup(self.journal.conn.close)
        self.bridge = Bridge('unused', SimpleNamespace(get=lambda tid: {}), self.journal)
        self.bridge.ipc = self.runtime; self.bridge.enabled = True
        self.writes = []; self.queue = []; self.error = None; self.hook = lambda: None
        self.result = {'reviewThreadId': T, 'turn': {'id': 'review-turn', 'status': 'inProgress', 'items': []}}
        self.runtime.rpc = self.rpc
        self.data = {'action': 'review', 'requestId': 'review-once', 'target': {'type': 'uncommittedChanges'}}

    def rpc(self, method, params, before_send=None, **kwargs):
        if method == 'thread/queue/list': return {'data': self.queue}
        self.hook()
        before_send(lambda: self.writes.append((method, copy.deepcopy(params))))
        if self.error: raise self.error
        return self.result

    def test_inline_exact_identity_and_no_replay(self):
        job = submit(self.bridge, T, self.data)
        self.assertEqual((job['state'], job['turnId'], job['reviewThreadId']), ('completed', 'review-turn', T))
        self.assertEqual(self.writes, [('review/start', {'threadId': T, 'delivery': 'inline', 'target': self.data['target']})])
        self.assertEqual(submit(self.bridge, T, self.data), job); self.assertEqual(len(self.writes), 1)
        self.assertEqual(capability('POST', '/api/threads/' + T + '/operations', self.data), 'send')

    def test_unknown_or_wrong_identity_blocks_replay_and_release(self):
        self.error = IPCError('lost', uncertain=True)
        job = submit(self.bridge, T, self.data)
        self.assertEqual(job['state'], 'uncertain'); self.assertTrue(self.runtime.current(T)['_metadataOnly'])
        self.assertEqual(submit(self.bridge, T, self.data), job); self.assertEqual(len(self.writes), 1)

    def test_other_review_thread_reply_is_uncertain(self):
        self.result['reviewThreadId'] = 'other-thread'
        job = submit(self.bridge, T, self.data)
        self.assertEqual(job['state'], 'uncertain')
        self.assertNotIn('turnId', job)
        self.assertEqual(submit(self.bridge, T, self.data), job)
        self.assertEqual(len(self.writes), 1)

    def test_replacement_session_receipt_or_exception_does_not_mutate_new_state(self):
        original = self.rpc
        for failed in (False, True):
            self.data['requestId'] = 'replace-' + str(failed)
            def rpc(method, params, before_send=None, **kwargs):
                result = original(method, params, before_send, **kwargs)
                if method == 'review/start':
                    self.runtime.session_id = 'replacement-' + str(failed)
                    if failed: raise IPCError('old receipt lost', uncertain=True)
                return result
            self.runtime.rpc = rpc
            job = submit(self.bridge, T, self.data)
            self.assertEqual(job['state'], 'uncertain', job)
            self.assertEqual(self.runtime.current(T)['turns'], [])
            self.assertFalse(self.runtime.current(T).get('_metadataOnly', False))
            self.assertEqual(self.runtime.current(T)['threadRuntimeStatus']['type'], 'idle')

    def test_post_receipt_revocation_is_uncertain_even_for_definite_local_error(self):
        original = self.rpc
        allowed = [True]
        def authorize():
            if not allowed[0]: raise IPCError('permission revoked')
        def rpc(method, params, before_send=None, **kwargs):
            result = original(method, params, before_send, **kwargs)
            if method == 'review/start': allowed[0] = False
            return result
        self.runtime.rpc = rpc
        job = submit(self.bridge, T, self.data, authorize=authorize)
        self.assertEqual(job['state'], 'uncertain', job)
        self.assertEqual(len(self.writes), 1)

    def test_canonical_refresh_removes_worker_but_replays_new_real_turn(self):
        from carryon.app_server.review_history import refresh
        state = self.runtime.current(T)
        completed = {'id': 'outer', 'status': 'completed', 'items': [{'id': 'review', 'type': 'enteredReviewMode'}]}
        state['turns'] = [{**completed, 'turnId': 'outer'}, {'turnId': 'worker', 'status': 'inProgress', 'items': []}]
        state['threadRuntimeStatus'] = {'type': 'idle'}
        def rpc(method, params):
            if method == 'thread/read':
                return {'thread': {'id': T, 'cwd': self.temp.name, 'status': {'type': 'idle'}}}
            self.runtime._event({'method': 'turn/started', 'params': {'threadId': T,
                'turn': {'id': 'new-real', 'status': 'inProgress', 'items': []}}})
            return {'data': [completed], 'nextCursor': None}
        self.runtime.rpc = rpc
        refresh(self.runtime, T, (self.runtime.process, self.runtime.session_id))
        current = self.runtime.current(T)
        self.assertEqual([turn['turnId'] for turn in current['turns']], ['outer', 'new-real'])
        self.assertEqual(current['threadRuntimeStatus']['type'], 'active')

    def test_canonical_refresh_failure_is_unknown_not_idle(self):
        from carryon.app_server.review_history import refresh
        self.runtime.rpc = lambda *_: (_ for _ in ()).throw(IPCError('read failed'))
        refresh(self.runtime, T, (self.runtime.process, self.runtime.session_id))
        self.assertTrue(self.runtime.current(T)['_metadataOnly'])
        self.assertEqual(self.runtime.current(T)['threadRuntimeStatus']['type'], 'notLoaded')

    def test_buffered_review_completion_gets_one_followup_canonical_read(self):
        from carryon.app_server.review_history import refresh
        reads = []; finished = threading.Event()
        original = {'id': 'old', 'status': 'completed', 'items': [{'id': 'r', 'type': 'enteredReviewMode'}]}
        new = {'id': 'new', 'status': 'completed', 'items': [{'id': 'nr', 'type': 'enteredReviewMode'}]}
        def rpc(method, params):
            if method == 'thread/read':
                return {'thread': {'id': T, 'cwd': self.temp.name, 'status': {'type': 'idle'}}}
            reads.append(method)
            if len(reads) == 1:
                for turn, method in [({**new, 'status': 'inProgress'}, 'turn/started'),
                                     ({'id': 'worker', 'status': 'inProgress', 'items': []}, 'turn/started'),
                                     (new, 'turn/completed')]:
                    self.runtime._event({'method': method, 'params': {'threadId': T, 'turn': turn}})
                return {'data': [original], 'nextCursor': None}
            finished.set()
            return {'data': [original, new], 'nextCursor': None}
        self.runtime.rpc = rpc
        previous = self.runtime.on_change
        settled = threading.Event()
        self.runtime.on_change = lambda: settled.set() if finished.is_set() and not self.runtime.review_refreshing else previous()
        refresh(self.runtime, T, (self.runtime.process, self.runtime.session_id))
        self.assertTrue(settled.wait(2))
        self.assertEqual(len(reads), 2)
        self.assertEqual([turn['turnId'] for turn in self.runtime.current(T)['turns']], ['old', 'new'])

    def test_generation_or_busy_state_at_write_prevents_review(self):
        self.hook = lambda: setattr(self.bridge, 'generation', self.bridge.generation + 1)
        self.assertEqual(submit(self.bridge, T, self.data)['state'], 'failed'); self.assertEqual(self.writes, [])
        self.hook = lambda: self.runtime.current(T).update(threadRuntimeStatus={'type': 'active'})
        self.data['requestId'] = 'busy-review'
        self.assertEqual(submit(self.bridge, T, self.data)['state'], 'failed'); self.assertEqual(self.writes, [])

    def test_queue_metadata_and_desktop_do_not_start(self):
        self.queue = [{'id': 'q', 'clientUserMessageId': 'q', 'input': [{'type': 'text', 'text': 'queued'}]}]
        self.assertEqual(submit(self.bridge, T, self.data)['state'], 'failed')
        self.queue = []; self.runtime.current(T)['_metadataOnly'] = True
        self.data['requestId'] = 'metadata-review'
        self.assertEqual(submit(self.bridge, T, self.data)['state'], 'failed')
        self.bridge.ipc = SimpleNamespace(connected=True); self.data['requestId'] = 'desktop-review'
        self.assertEqual(submit(self.bridge, T, self.data)['state'], 'failed'); self.assertEqual(self.writes, [])

    def test_native_targets_are_strict_and_review_items_disable_steer(self):
        for target in [{'type': 'uncommittedChanges'}, {'type': 'baseBranch', 'branch': 'main'},
                       {'type': 'commit', 'sha': 'abcd', 'title': None}, {'type': 'custom', 'instructions': 'Review'}]:
            self.assertEqual(request(T, {**self.data, 'target': target})['target'], target)
        for target in [{'type': 'unknown'}, {'type': 'baseBranch'}, {'type': 'commit', 'sha': ''},
                       {'type': 'uncommittedChanges', 'branch': 'main'}]:
            with self.assertRaises(ValueError): request(T, {**self.data, 'target': target})
        with self.assertRaises(ValueError): request(T, {**self.data, 'delivery': 'detached'})
        state = self.runtime.current(T)
        state['threadRuntimeStatus'] = {'type': 'active'}
        state['turns'] = [{'turnId': 'review', 'status': 'inProgress', 'items': [{'type': 'enteredReviewMode'}]}]
        self.assertFalse(controls(state)['canSteer']); self.assertEqual(controls(state)['activeTurnKind'], 'review')
        with self.assertRaises(ValueError): build('steer', {'expectedTurnId': 'review', 'prompt': 'more'}, state)
