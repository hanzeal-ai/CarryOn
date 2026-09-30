import copy
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from carryon.owner.manager import OwnerManager
from carryon.owner.requests import forward
from carryon.desktop_ipc.ipc import IPCError
from carryon.owner.state import conversation

T = '11111111-1111-4111-8111-111111111111'
U = '22222222-2222-4222-8222-222222222222'


def state(tid=T):
    return {'id': tid, 'cwd': '/project', 'turns': [{'turnId': 'old', 'status': 'completed', 'items': []}],
            'requests': [], 'threadRuntimeStatus': {'type': 'idle'},
            'threadMetadata': {'createdAt': 1, 'updatedAt': 2}, 'supportedOperations': ['interrupt']}


class Runtime:
    instances = []
    def __init__(self, *args, **kwargs):
        self.lock = threading.RLock()
        self.connected = False; self.data = None; self.calls = []; self.on_change = lambda: None
        self.instances.append(self)
    def connect(self): self.connected = True
    def close(self): self.connected = False
    def snapshot(self, tid): self.data = state(tid); return 'app-server', self.data
    def current(self, tid): return self.data
    def require_account(self): pass
    def rpc(self, method, params):
        self.calls.append((method, params))
        if method == 'turn/start': return {'turn': {'id': 'new', 'status': 'inProgress', 'items': []}}
        if method == 'thread/loaded/list': return {'data': [self.data['id']]}
        return {}
    def _event(self, event):
        turn = event['params']['turn']; self.data['turns'].append({**turn, 'turnId': turn['id']})
    def respond(self, tid, params, guard, timeout):
        self.calls.append(('respond', params)); return {'result': {}}


class Bus:
    def __init__(self, path): self.requests_in_flight = 0; self.connected = False; self.client_id = 'bridge-owner'; self.messages = []; self.foreign = None
    def connect(self): self.connected = True
    def close(self): self.connected = False
    def owner(self, tid, **kwargs):
        if self.foreign: return self.foreign
        raise IPCError('no-client-found')
    def _write(self, msg): self.messages.append(copy.deepcopy(msg))


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.catalog = Mock(); self.catalog.get.return_value = {'history_mode': 'paginated'}
        self.manager = OwnerManager('/home', Path(self.tmp.name), self.catalog, runtime_factory=Runtime, transport_factory=Bus)
        self.addCleanup(self.manager.close)
    def envelope(self, method='thread-owner-discovery', version=1, tid=T, **params):
        return {'method': method, 'version': version, 'requestId': 'wire-1', 'sourceClientId': 'desktop',
                'params': {'hostId': 'local', 'conversationId': tid, **params}}
    def test_load_publish_discovery_and_release(self):
        self.manager.load(T)
        self.assertTrue(self.manager.can_handle(self.envelope()))
        self.assertEqual(self.manager.handle(self.envelope()), {'supportsUntrustedAppInput': False})
        message = self.manager.bus.messages[-1]
        self.assertEqual(message['params']['change']['conversationState']['turnHistory']['history']['isComplete'], True)
        self.assertEqual(self.manager.entries[T]['runtime'].calls, [])
        self.manager.release(T)
        self.assertFalse(self.manager.can_handle(self.envelope()))
        self.assertFalse(self.manager.bus.connected)
    def test_existing_owner_and_legacy_are_not_resumed(self):
        self.manager.bus.foreign = 'desktop'
        self.assertEqual(self.manager.load(T)['state'], 'desktop')
        self.assertEqual(self.manager.entries, {})
        self.manager.bus.foreign = None; self.catalog.get.return_value = {'history_mode': 'legacy'}
        with self.assertRaises(IPCError): self.manager.load(T)
        self.assertEqual(self.manager.entries, {})
    def test_revoke_before_claim_closes_runtime(self):
        count = [0]
        def guard():
            count[0] += 1
            if count[0] == 3: raise PermissionError('revoked')
        with self.assertRaises(PermissionError): self.manager.load(T, guard)
        self.assertEqual(self.manager.entries, {})
        self.assertFalse(Runtime.instances[-1].connected)
    def test_method_version_host_and_thread_are_checked(self):
        self.manager.load(T)
        for e in (self.envelope(version=0), self.envelope(tid=U), self.envelope(method='thread/delete'), self.envelope(hostId='remote')):
            self.assertFalse(self.manager.can_handle(e))
            with self.assertRaises(IPCError): self.manager.handle(e)
    def test_start_is_forwarded_once_and_cross_thread_context_rejected(self):
        self.manager.load(T); runtime = self.manager.entries[T]['runtime']
        bad = self.envelope('thread-follower-start-turn', 2, turnStart={'request': {'threadId': U, 'input': []}})
        with self.assertRaises(IPCError): self.manager.handle(bad)
        self.assertEqual(runtime.calls, [])
        good = self.envelope('thread-follower-start-turn', 2, turnStart={'request': {
            'threadId': T, 'clientUserMessageId': 'message-1', 'input': [{'type': 'text', 'text': 'hello'}]}})
        self.manager.handle(good); self.manager.handle(good)
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(runtime.calls[0][0], 'turn/start')
    def test_running_release_and_stale_steer_rejected(self):
        self.manager.load(T); runtime = self.manager.entries[T]['runtime']
        runtime.data['turns'].append({'turnId': 'active', 'status': 'inProgress', 'items': []})
        with self.assertRaises(IPCError): self.manager.release(T)
        with self.assertRaises(IPCError): forward(runtime, T, 'thread-follower-steer-turn', {'expectedTurnId': 'old', 'input': []})
        forward(runtime, T, 'thread-follower-interrupt-turn', {'expectedTurnId': 'active'})
        self.assertEqual(runtime.calls, [('turn/interrupt', {'threadId': T, 'turnId': 'active'})])
    def test_peer_conflict_freezes_writes_but_keeps_runtime(self):
        self.manager.load(T)
        self.manager.broadcast({'method': 'thread-stream-state-changed', 'version': 11, 'sourceClientId': 'peer',
                                'params': {'hostId': 'local', 'conversationId': T}})
        self.assertFalse(self.manager.can_handle(self.envelope()))
        self.assertTrue(self.manager.entries[T]['runtime'].connected)
    def test_native_steer_without_expected_id_uses_current_turn(self):
        runtime = Runtime(); runtime.snapshot(T)
        runtime.data['turns'].append({'turnId': 'active', 'status': 'inProgress', 'items': []})
        forward(runtime, T, 'thread-follower-steer-turn', {'input': [{'type': 'text', 'text': 'next'}]})
        self.assertEqual(runtime.calls[0][1]['expectedTurnId'], 'active')
    def test_crashed_runtime_invalidates_last_snapshot(self):
        self.manager.load(T)
        runtime = self.manager.entries[T]['runtime']; runtime.close(); runtime.data = None
        self.manager.publish(T)
        value = self.manager.bus.messages[-1]['params']['change']['conversationState']
        self.assertEqual(value['threadRuntimeStatus'], {'type': 'notLoaded'})
        self.assertEqual(value['supportedOperations'], [])
    def test_start_response_does_not_overwrite_completed_notification(self):
        runtime = Runtime(); runtime.snapshot(T)
        original = runtime.rpc
        def rpc(method, params):
            result = original(method, params)
            runtime.data['turns'].append({'turnId': 'new', 'status': 'completed', 'items': [{'id': 'answer'}]})
            return result
        runtime.rpc = rpc
        forward(runtime, T, 'thread-follower-start-turn', {'turnStart': {'request': {'threadId': T, 'input': []}}})
        self.assertEqual(runtime.data['turns'][-1]['status'], 'completed')
        self.assertEqual(runtime.data['turns'][-1]['items'], [{'id': 'answer'}])
    def test_releasing_one_does_not_stop_another_runtime(self):
        self.manager.load(T); self.manager.load(U)
        first = self.manager.entries[T]['runtime']; second = self.manager.entries[U]['runtime']
        self.manager.release(T)
        self.assertFalse(first.connected); self.assertTrue(second.connected)
    def test_permissions_response_cannot_exceed_requested_permissions(self):
        runtime = Runtime(); runtime.snapshot(T)
        runtime.data['requests'] = [{'id': 4, 'method': 'item/permissions/requestApproval', 'params': {'permissions': {}}}]
        with self.assertRaises(ValueError): forward(runtime, T, 'thread-follower-permissions-request-approval-response',
            {'requestId': 4, 'response': {'permissions': {'network': {'enabled': True}}, 'scope': 'session'}})
        self.assertEqual(runtime.calls, [])
    def test_snapshot_does_not_mutate_authoritative_runtime(self):
        original = state(); before = copy.deepcopy(original); projected = conversation(original)
        self.assertEqual(original, before)
        self.assertEqual(projected['turnHistory']['history']['entitiesByKey']['old']['turnId'], 'old')
        self.assertEqual(projected['executionBackend'], 'carryon-owner')


class OwnerBoundaryTests(unittest.TestCase):
    setUp = OwnerTests.setUp
    envelope = OwnerTests.envelope
    def test_receipt_content_mismatch_and_known_failure_remain_known(self):
        self.manager.load(T)
        bad = self.envelope('thread-follower-start-turn', 2, turnStart={'request': {'threadId': U, 'input': []}})
        for _ in range(2):
            with self.assertRaises(IPCError) as caught: self.manager.handle(bad)
            self.assertFalse(caught.exception.uncertain)
        changed = copy.deepcopy(bad); changed['params']['turnStart']['request']['threadId'] = T
        with self.assertRaisesRegex(IPCError, 'content-mismatch'): self.manager.handle(changed)
        self.assertEqual(self.manager.entries[T]['runtime'].calls, [])

    def test_malformed_discovery_and_broadcast_do_not_claim_or_crash(self):
        self.manager.load(T)
        for envelope in (None, [], self.envelope(version=True), self.envelope(tid=[]), self.envelope(method=[])):
            self.assertFalse(self.manager.can_handle(envelope))
        self.manager.broadcast({'params': ['invalid']})
        self.manager.broadcast({'params': {'conversationId': []}})
        self.assertTrue(self.manager.can_handle(self.envelope()))

    def test_user_input_native_wire_roundtrip(self):
        from carryon.sessions.operations import build
        from carryon.contracts import digest
        runtime = Runtime(); runtime.snapshot(T)
        request = {'id': 12, 'method': 'item/tool/requestUserInput', 'params': {
            'questions': [{'id': 'choice', 'question': 'Select one'}]}}
        runtime.data['requests'] = [request]
        method, _, wire = build('user-input', {'nativeRequestId': 12,
            'requestFingerprint': digest(request), 'answers': {'choice': ['A']}}, runtime.data)
        forward(runtime, T, method, wire)
        self.assertEqual(runtime.calls[0][1]['response'], {'answers': {'choice': {'answers': ['A']}}})

    def test_complete_history_has_exhausted_boundaries(self):
        history = conversation(state())['turnHistory']['history']
        for island in history['islands']:
            for edge in ('olderBoundary', 'newerBoundary'):
                self.assertEqual(island[edge]['status'], 'exhausted')
                self.assertTrue(island[edge]['boundaryId'])


class OwnerIntegrationTests(unittest.TestCase):
    def test_bridge_off_preserves_owner_and_shutdown_closes_it(self):
        from carryon.owner.integration import OwnerBridge
        from carryon.store import Journal
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / 'jobs.db'); self.addCleanup(journal.conn.close)
            bridge = OwnerBridge('unused', Mock(), journal, owner_directory=directory)
            service = Mock(); bridge.owner_service = service
            bridge.disable(); service.close.assert_not_called()
            bridge.shutdown(); service.close.assert_called_once()

    def test_session_endpoint_requires_remote_write_and_optional_capability(self):
        from carryon.routes.api import dispatch
        from carryon.errors import BridgeError
        bridge = Mock(); path = '/api/threads/' + T + '/session'
        with self.assertRaises(BridgeError): dispatch(bridge, 'POST', path, remote=True)
        bridge.session_control.assert_not_called()
        guard = Mock()
        dispatch(bridge, 'POST', path, {'action': 'load'}, remote=True, control=True, authorize=guard)
        self.assertIs(bridge.session_control.call_args.args[-1], guard)
        del bridge.session_control
        with self.assertRaises(BridgeError): dispatch(bridge, 'POST', path)

    def test_session_receipt_and_authorization_are_rechecked(self):
        from carryon.owner.integration import OwnerBridge
        from carryon.store import Journal
        from carryon.errors import BridgeError
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / 'jobs.db'); self.addCleanup(journal.conn.close)
            bridge = OwnerBridge('unused', Mock(), journal, owner_directory=directory)
            bridge.require = Mock(return_value=(Mock(), 1)); bridge.assert_target = Mock(); bridge.check_generation = Mock()
            bridge.owner_service = Mock(); bridge.owner_service.load.return_value = {'state': 'loaded'}
            guard = Mock(); data = {'requestId': 'owner-test-request-1', 'action': 'load'}
            self.assertEqual(bridge.session_control(T, data, authorize=guard)['state'], 'completed')
            bridge.session_control(T, data, authorize=guard)
            bridge.owner_service.load.assert_called_once()
            with self.assertRaises(BridgeError): bridge.session_control(T, {**data, 'action': 'release'})
            with self.assertRaises(PermissionError): bridge.session_control(T, data, authorize=Mock(side_effect=PermissionError()))

class AutoReleaseTests(unittest.TestCase):
    envelope = OwnerTests.envelope

    def setUp(self):
        OwnerTests.setUp(self)
        # Drive publisher iterations explicitly to cover precise notification ordering.
        self.manager.worker = threading.Thread(target=lambda: None)
        self.manager.worker.start(); self.manager.worker.join()
        self.manager.load(T)
        self.runtime = self.manager.entries[T]['runtime']

    def start(self):
        request = self.envelope('thread-follower-start-turn', 2, turnStart={'request': {
            'threadId': T, 'clientUserMessageId': 'auto-release-message', 'input': [{'type': 'text', 'text': 'hello'}]}})
        self.manager.handle(request)
        return request

    def finish(self, status='completed'):
        self.runtime.data['turns'][-1]['status'] = status
        self.runtime.data['threadRuntimeStatus'] = {'type': 'idle'}

    def test_load_only_does_not_release_old_finished_history(self):
        self.manager._release_finished()
        self.assertIn(T, self.manager.entries)

    def test_terminal_and_idle_are_both_required(self):
        self.start()
        self.manager._release_finished()  # idle can arrive before completed
        self.assertTrue(self.runtime.connected)
        self.finish(); self.runtime.data['threadRuntimeStatus'] = {'type': 'active'}
        self.manager._release_finished()
        self.assertTrue(self.runtime.connected)
        self.runtime.data['threadRuntimeStatus'] = {'type': 'idle'}
        self.manager._release_finished()
        self.assertNotIn(T, self.manager.entries)
        self.assertFalse(self.runtime.connected)
        final = self.manager.bus.messages[-1]['params']['change']['conversationState']
        self.assertEqual(final['turns'][-1]['status'], 'completed')
        self.assertEqual(final['threadRuntimeStatus']['type'], 'notLoaded')

    def test_approvals_and_unsent_responses_block_release(self):
        self.start(); self.finish()
        self.runtime.data['requests'] = [{'id': 4}]
        self.manager._release_finished(); self.assertTrue(self.runtime.connected)
        self.runtime.data['requests'] = []
        self.manager.bus.requests_in_flight = 1
        self.manager._release_finished(); self.assertTrue(self.runtime.connected)
        self.manager.bus.requests_in_flight = 0
        self.manager._release_finished(); self.assertFalse(self.runtime.connected)

    def test_response_retry_after_reload_does_not_execute_twice(self):
        request = self.start(); self.finish(); self.manager._release_finished()
        self.manager.load(T); runtime = self.manager.entries[T]['runtime']
        # Native history after resume includes the completed original turn.
        runtime.data['turns'].append({'turnId': 'new', 'status': 'completed', 'items': []})
        self.manager.handle(request)
        self.assertEqual(runtime.calls, [])
        changed = copy.deepcopy(request)
        changed['params']['turnStart']['request']['input'][0]['text'] = 'different'
        with self.assertRaisesRegex(IPCError, 'content-mismatch'): self.manager.handle(changed)
        self.manager._release_finished(); self.assertFalse(runtime.connected)

    def test_disconnected_bus_does_not_keep_finished_writer(self):
        self.start(); self.finish(); self.manager.bus.connected = False
        self.manager._release_finished()
        self.assertFalse(self.runtime.connected)

    def test_invalidation_failure_still_releases_writer(self):
        self.start(); self.finish()
        self.manager.bus._write = Mock(side_effect=IPCError('socket lost'))
        self.manager._release_finished()
        self.assertFalse(self.runtime.connected)
        self.assertNotIn(T, self.manager.entries)

    def test_failed_and_interrupted_tasks_release_without_affecting_other_session(self):
        self.manager.load(U); other = self.manager.entries[U]['runtime']
        self.start(); self.finish('failed'); self.manager._release_finished()
        self.assertFalse(self.runtime.connected); self.assertTrue(other.connected)
        self.assertTrue(self.manager.bus.connected)
        self.manager.load(T); self.runtime = self.manager.entries[T]['runtime']
        self.manager.entries[T]['submitted_turn_ids'].add('interrupted')
        self.runtime.data['turns'].append({'turnId': 'interrupted', 'status': 'interrupted', 'items': []})
        self.manager._release_finished()
        self.assertFalse(self.runtime.connected); self.assertTrue(other.connected)

    def test_lost_start_response_releases_after_native_terminal_evidence(self):
        def uncertain_start(method, params):
            self.runtime.data['turns'].append({'turnId': 'lost-reply', 'status': 'completed', 'items': []})
            raise IPCError('reply lost', uncertain=True)
        self.runtime.rpc = uncertain_start
        with self.assertRaises(IPCError): self.start()
        self.manager._release_finished()
        self.assertFalse(self.runtime.connected)

    def test_full_execution_receipts_do_not_block_interrupt_or_approval(self):
        self.start()
        receipts = self.manager.entries[T]['receipts']
        for number in range(1000 - len(receipts)): receipts[('full', number)] = {}
        self.manager.handle(self.envelope('thread-follower-interrupt-turn', 4, expectedTurnId='new'))
        self.assertEqual(self.runtime.calls[-1][0], 'turn/interrupt')
        self.runtime.data['requests'] = [{'id': 12, 'method': 'item/tool/requestUserInput',
            'params': {'questions': [{'id': 'choice', 'question': 'Select'}]}}]
        request = self.envelope('thread-follower-submit-user-input', 1, requestId=12,
            response={'answers': {'choice': {'answers': ['A']}}})
        request['requestId'] = 'approval-wire'
        self.manager.handle(request); self.manager.handle(request)
        self.assertEqual(sum(method == 'respond' for method, _ in self.runtime.calls), 1)
        self.assertEqual(len(receipts), 1000)

    def test_native_state_race_keeps_worker_and_other_releases_available(self):
        self.start(); self.finish()
        self.manager.load(U)
        other = self.manager.entries[U]
        other['submitted_turn_ids'].add('old')
        original = self.runtime.current; count = [0]
        def current(tid):
            count[0] += 1
            value = original(tid)
            if count[0] == 2:
                value['threadRuntimeStatus'] = {'type': 'active'}
            return value
        self.runtime.current = current
        self.manager._release_finished()
        self.assertTrue(self.runtime.connected)
        self.assertNotIn(U, self.manager.entries)
        self.runtime.current = original; self.finish()
        self.manager._release_finished()
        self.assertFalse(self.runtime.connected)

    def test_unrelated_history_change_is_not_an_accepted_task(self):
        self.runtime.data['turns'].append({'turnId': 'extra', 'status': 'completed', 'items': []})
        self.manager._release_finished(); self.assertTrue(self.runtime.connected)


if __name__ == '__main__': unittest.main()


class SendOwnerTests(unittest.TestCase):
    def setUp(self):
        from carryon.owner.integration import OwnerBridge
        from carryon.store import Journal
        from test_bridge import Catalog, FakeIPC
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.journal = Journal(Path(self.tmp.name) / 'jobs.db'); self.addCleanup(self.journal.conn.close)

        class UnloadedIPC(FakeIPC):
            loaded = False
            sends = 0
            error = None
            runtime = 'idle'
            def snapshot(self, tid):
                if not self.loaded: raise IPCError('no-client-found')
                return super().snapshot(tid)

        self.bridge = OwnerBridge('unused', Catalog(), self.journal, owner_directory=self.tmp.name, ipc_factory=UnloadedIPC)
        self.bridge.enable(); self.addCleanup(self.bridge.shutdown)
        self.ipc = self.bridge.ipc
        self.service = Mock(); self.bridge.owner_service = self.service
        def load(tid, check):
            check()
            self.ipc.loaded = True
            return {'state': 'loaded'}
        self.service.load.side_effect = load

    def test_compose_endpoint_loads_then_sends_and_retry_does_not_reload(self):
        from carryon.routes.api import dispatch
        guard = Mock()
        payload = {'requestId': 'auto-send-request', 'prompt': 'hello'}
        path = '/api/threads/' + T + '/compose'
        code, job = dispatch(self.bridge, 'POST', path, payload, remote=True, control=True, authorize=guard)
        self.assertEqual((code, job['state']), (202, 'accepted'))
        self.assertEqual(type(self.ipc).sends, 1)
        self.service.load.assert_called_once()
        self.assertGreaterEqual(guard.call_count, 3)
        self.ipc.loaded = False  # Owner was automatically released after completion.
        self.assertEqual(dispatch(self.bridge, 'POST', path, payload, remote=True, control=True)[1], job)
        self.assertEqual(type(self.ipc).sends, 1)
        self.service.load.assert_called_once()
        payload['requestId'] = 'auto-send-next-request'
        self.assertEqual(dispatch(self.bridge, 'POST', path, payload, remote=True, control=True)[1]['state'], 'accepted')
        self.assertEqual(type(self.ipc).sends, 2)
        self.assertEqual(self.service.load.call_count, 2)

    def test_messages_endpoint_also_loads_before_sending(self):
        from carryon.routes.api import dispatch
        _, job = dispatch(self.bridge, 'POST', '/api/threads/' + T + '/messages',
                          {'requestId': 'auto-message-request', 'prompt': 'hello'})
        self.assertEqual(job['state'], 'accepted')
        self.service.load.assert_called_once()

    def test_existing_owner_is_used_without_loading(self):
        self.ipc.loaded = True
        self.assertEqual(self.bridge.compose(T, 'existing-owner-request', 'hello')['state'], 'accepted')
        self.service.load.assert_not_called()

    def test_other_or_uncertain_errors_never_load(self):
        for error in (IPCError('request-timeout', uncertain=True), IPCError('permission denied'),
                      IPCError('no-client-found', uncertain=True)):
            with self.subTest(error=str(error), uncertain=error.uncertain):
                self.ipc.snapshot = Mock(side_effect=error)
                with self.assertRaises(IPCError): self.bridge.compose(T, 'no-load-error-request', 'hello')
        self.service.load.assert_not_called()
        self.assertEqual(type(self.ipc).sends, 0)

    def test_revoked_or_readonly_requests_do_not_load(self):
        from carryon.routes.api import dispatch
        from carryon.errors import BridgeError
        path = '/api/threads/' + T + '/compose'
        payload = {'requestId': 'revoked-send-request', 'prompt': 'hello'}
        with self.assertRaises(BridgeError): dispatch(self.bridge, 'POST', path, payload, remote=True)
        with self.assertRaises(PermissionError):
            self.bridge.compose(T, payload['requestId'], 'hello', authorize=Mock(side_effect=PermissionError('revoked')))
        self.service.load.assert_not_called()
        self.assertEqual(type(self.ipc).sends, 0)

    def test_disable_during_load_blocks_send(self):
        from carryon.errors import BridgeError
        def load(tid, check):
            self.bridge.disable()
            check()
        self.service.load.side_effect = load
        with self.assertRaises(BridgeError): self.bridge.compose(T, 'disabled-send-request', 'hello')
        self.assertEqual(type(self.ipc).sends, 0)

    def test_revoke_after_load_blocks_send(self):
        guard = Mock()
        def load(tid, check):
            check()
            self.ipc.loaded = True
            guard.side_effect = PermissionError('revoked')
        self.service.load.side_effect = load
        with self.assertRaises(PermissionError): self.bridge.compose(T, 'revoke-after-load', 'hello', authorize=guard)
        self.assertEqual(type(self.ipc).sends, 0)

    def test_load_failure_or_competition_never_sends(self):
        for error in ('owner appeared during resume', 'owner-conflict', 'owner requires paginated history with native writer locking'):
            self.service.load.side_effect = IPCError(error)
            with self.assertRaisesRegex(IPCError, error): self.bridge.compose(T, 'load-failure-request', 'hello')
        self.assertEqual(type(self.ipc).sends, 0)

    def test_uncertain_start_is_not_replayed_or_reloaded(self):
        type(self.ipc).error = IPCError('request-timeout', uncertain=True)
        job = self.bridge.compose(T, 'uncertain-start-request', 'hello')
        self.assertEqual(job['state'], 'uncertain')
        self.ipc.loaded = False
        self.assertEqual(self.bridge.compose(T, 'uncertain-start-request', 'hello'), job)
        self.assertEqual(type(self.ipc).sends, 1)
        self.service.load.assert_called_once()

    def test_side_conversation_does_not_trigger_resume(self):
        with self.assertRaises(IPCError):
            self.bridge.send_snapshot(self.ipc, self.bridge.generation, T, parent_id=U)
        self.service.load.assert_not_called()

    def test_release_between_compose_and_dispatch_is_reloaded(self):
        snapshot = self.ipc.snapshot
        calls = 0
        def release_after_snapshot(tid):
            nonlocal calls
            result = snapshot(tid)
            calls += 1
            if calls == 1: self.ipc.loaded = False
            return result
        self.ipc.snapshot = release_after_snapshot
        self.assertEqual(self.bridge.compose(T, 'release-race-request', 'hello')['state'], 'accepted')
        self.assertEqual(type(self.ipc).sends, 1)
        self.assertEqual(self.service.load.call_count, 2)
