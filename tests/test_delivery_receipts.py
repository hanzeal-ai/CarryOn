"""Native receipts, uncertain transport outcomes, and independent command gates."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from carryon.routes.api import dispatch as api
from carryon.sessions.bridge import BridgeError
from carryon.contracts import digest
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError
from carryon.sessions.operations import submit
from carryon.store import Journal
import test_bridge as message_fixture
from test_bridge import FakeIPC, THREAD
import test_operations as operation_fixture
from test_operations import T, state


class MessageReceiptTests(unittest.TestCase):
    setUp = message_fixture.BridgeTests.setUp
    tearDown = message_fixture.BridgeTests.tearDown
    def test_response_is_native_receipt_and_not_registration(self):
        self.bridge.enable()
        code, receipt = api(self.bridge, 'POST', f'/api/threads/{THREAD}/messages',
                            {'requestId': 'direct-receipt', 'prompt': 'hello'})
        self.assertEqual(code, 202)
        self.assertEqual(receipt['state'], 'accepted')
        self.assertEqual(FakeIPC.sends, 1)
        self.assertEqual(receipt['evidence'], 'native-handler-response')
        self.bridge.turn_evidence = Mock(side_effect=AssertionError('receipt must not track execution'))
        self.assertEqual(self.bridge.refresh_job(receipt['id'])['state'], 'accepted')
        self.assertEqual(self.bridge.submit('message', 'second-receipt', 'next', THREAD)['state'], 'accepted')

    def test_direct_creation_receipt_does_not_follow_later_task_execution(self):
        self.bridge.enable()
        job = {'id': 'created-directly', 'fingerprint': 'f', 'kind': 'create', 'threadId': THREAD,
               'createdThreadId': THREAD, 'state': 'accepted', 'turnId': 'turn', 'created': time.time()}
        self.journal.insert(job)
        self.bridge.turn_evidence = Mock(side_effect=AssertionError('creation already acknowledged'))
        self.assertEqual(self.bridge.refresh_job(job['id']), job)

    def test_restart_preparation_is_known_unsent(self):
        self.journal.insert({'id': 'not-written', 'fingerprint': 'f', 'kind': 'message',
                             'threadId': THREAD, 'state': 'preparing', 'created': time.time()})
        other = Journal(self.journal.conn.execute('PRAGMA database_list').fetchone()[2])
        try:
            self.assertEqual(other.get('not-written')['state'], 'failed')
            self.assertEqual(FakeIPC.sends, 0)
        finally:
            other.conn.close()

    def test_lost_receipt_recovers_native_client_id_without_turn_id(self):
        self.bridge.enable()
        FakeIPC.error = IPCError('timeout', uncertain=True)
        job = self.bridge.submit('message', 'lost-receipt', 'hello', THREAD)
        self.assertEqual(job['state'], 'uncertain')
        self.bridge.ipc.snapshot = Mock(return_value=('owner', {'id': THREAD, 'turns': [
            {'turnId': 'native-turn', 'items': [{'type': 'userMessage', 'clientId': job['clientMessageId']}]}]}))
        recovered = self.bridge.refresh_job(job['id'])
        self.assertEqual(recovered['state'], 'accepted')
        self.assertEqual(recovered['turnId'], 'native-turn')
        self.assertEqual(FakeIPC.sends, 1)

    def test_recovery_does_not_match_same_text(self):
        self.bridge.enable()
        FakeIPC.error = IPCError('timeout', uncertain=True)
        job = self.bridge.submit('message', 'unmatched-receipt', 'hello', THREAD)
        self.bridge.ipc.snapshot = Mock(return_value=('owner', {'id': THREAD, 'turns': [
            {'turnId': 'other', 'items': [{'type': 'userMessage', 'clientId': 'other', 'text': 'hello'}]}]}))
        self.assertEqual(self.bridge.refresh_job(job['id'])['state'], 'uncertain')
        self.bridge.ipc.snapshot.assert_called_once()


class OperationReceiptTests(unittest.TestCase):
    setUp = operation_fixture.DeliveryTests.setUp
    tearDown = operation_fixture.DeliveryTests.tearDown
    def test_unknown_send_does_not_block_stop_or_approval(self):
        self.journal.insert({'id': 'unknown-send', 'fingerprint': 'f', 'kind': 'message',
                             'threadId': T, 'state': 'uncertain', 'created': time.time()})
        self.bridge.ipc.state = state('active')
        stopped = submit(self.bridge, T, {'action': 'interrupt', 'requestId': 'stop-despite-unknown', 'expectedTurnId': 'turn-1'})
        self.assertEqual(stopped['state'], 'completed')
        request = {'id': 7, 'method': 'item/commandExecution/requestApproval', 'params': {}}
        self.bridge.ipc.state['requests'] = [request]
        approved = submit(self.bridge, T, {'action': 'command-approval', 'requestId': 'approve-despite-unknown',
                                         'nativeRequestId': 7, 'requestFingerprint': digest(request), 'decision': 'decline'})
        self.assertEqual(approved['state'], 'completed')

    def test_queue_writes_use_persisted_native_state_not_delayed_broadcast(self):
        ipc = self.bridge.ipc
        persisted = []
        self.bridge.catalog.queued = lambda _: persisted
        ipc.events = SimpleNamespace(queues={T: []})
        ipc.lock = threading.RLock()
        native = ipc.request
        def request(method, params, *args):
            result = native(method, params, *args)
            persisted[:] = params['state'][T]
            return result
        ipc.request = request
        first = submit(self.bridge, T, {'action': 'queue-add', 'requestId': 'queue-first', 'prompt': 'one', 'queueFingerprint': digest([])})
        self.assertEqual(first['state'], 'completed')
        stale = submit(self.bridge, T, {'action': 'queue-add', 'requestId': 'queue-stale', 'prompt': 'two', 'queueFingerprint': digest([])})
        self.assertEqual(stale['state'], 'failed')
        fresh = submit(self.bridge, T, {'action': 'queue-add', 'requestId': 'queue-fresh', 'prompt': 'two', 'queueFingerprint': digest(persisted)})
        self.assertEqual(fresh['state'], 'completed')
        self.assertEqual([m['text'] for m in persisted], ['one', 'two'])

    def test_queue_conflict_gate_does_not_gate_stop(self):
        self.bridge.catalog.queued = lambda _: []
        self.journal.insert({'id': 'queue-pending', 'fingerprint': 'f', 'kind': 'operation:queue-add',
                             'threadId': T, 'state': 'dispatching', 'created': time.time()})
        for status in ('dispatching', 'uncertain'):
            self.journal.update('queue-pending', state=status)
            with self.assertRaises(BridgeError):
                submit(self.bridge, T, {'action': 'queue-add', 'requestId': 'another-queue-' + status, 'prompt': 'two', 'queueFingerprint': digest([])})
            self.bridge.ipc.state = state('active')
            self.assertEqual(submit(self.bridge, T, {'action': 'interrupt', 'requestId': 'stop-' + status, 'expectedTurnId': 'turn-1'})['state'], 'completed')


