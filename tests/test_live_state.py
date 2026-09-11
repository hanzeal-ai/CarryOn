"""Concurrency contracts using real Bridge/Journal and isolated native evidence."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from connectnow.bridge import Bridge, BridgeError
from connectnow.store import Journal

T = '11111111-1111-4111-8111-111111111111'


class LiveStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.temp.name) / 'jobs.sqlite')
        self.bridge = Bridge('unused', None, self.journal)
        self.ipc = SimpleNamespace(connected=True, watch=Mock(), unwatch=Mock(), close=Mock(),
            current=lambda tid: {'id': tid, 'threadRuntimeStatus': {'type': 'idle'}})
        self.bridge.ipc = self.ipc
        self.bridge.enabled = True
        self.sessions = []
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        owners = {s.owner for s in self.sessions}
        for session in self.sessions: session.close()
        self.bridge.disable()
        for owner in owners:
            for worker in owner.workers: worker.join(3)
            self.assertTrue(all(not worker.is_alive() for worker in owner.workers))
        self.journal.conn.close()
        self.temp.cleanup()

    def open(self):
        session = self.bridge.open_stream()
        self.sessions.append(session)
        return session

    def test_shared_watch_survives_one_client_closing(self):
        first, second = self.open(), self.open()
        for index, session in enumerate((first, second)):
            session.subscribe({'type':'subscribe', 'threadIds':[T], 'subscription':str(index)})
        self.assertIs(first.owner, second.owner)
        self.ipc.watch.assert_called_once_with(T)
        first.close()
        self.ipc.unwatch.assert_not_called()
        packet = second.update()[0]
        self.assertEqual(packet['threadStatuses'][T]['state'], 'idle')
        second.close()
        self.ipc.unwatch.assert_called_once_with(T)
        self.assertTrue(second.owner.closed.is_set())

    def test_slow_job_reconciliation_does_not_block_two_streams_or_repeat_reads(self):
        self.journal.insert({'id':'request-slow', 'fingerprint':'f', 'kind':'message',
            'threadId':T, 'created':time.time(), 'state':'accepted', 'turnId':'turn'})
        entered = threading.Event()
        def history(_):
            entered.set()
            if not self.release.wait(3): raise RuntimeError('test timeout')
            return {'turns': {'turn': {'status': 'completed'}}}
        self.bridge.history = Mock(side_effect=history)
        first, second = self.open(), self.open()
        self.assertTrue(entered.wait(2))
        for index, session in enumerate((first, second)):
            session.subscribe({'type':'subscribe', 'threadIds':[T], 'subscription':str(index)})
            # A slow reconciliation is still pending, but a live projection is ready.
            packet = session.update()[0]
            self.assertEqual(packet['jobs'][0]['state'], 'accepted')
            self.assertEqual(packet['threadStatuses'][T]['state'], 'idle')
        self.assertEqual(self.bridge.refresh_job('request-slow')['state'], 'accepted')
        self.bridge.history.assert_called_once_with(T)
        self.release.set()
        deadline = time.monotonic() + 2
        while self.journal.get('request-slow')['state'] != 'completed' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(second.update()[0]['jobs'][0]['state'], 'completed')
        self.bridge.history.assert_called_once_with(T)

    def test_stale_subscription_and_revoked_snapshot_are_never_delivered(self):
        session = self.open()
        old = session.update()
        session.subscribe({'type':'subscribe', 'threadIds':[T], 'subscription':'new'})
        sent = Mock()
        session.deliver(old, sent)
        sent.assert_not_called()
        old = session.update()
        self.bridge.disable()
        with self.assertRaises(BridgeError): session.deliver(old, sent)
        sent.assert_not_called()
        packet = session.update()[0]
        self.assertFalse(packet['status']['enabled'])
        self.assertNotIn('jobs', packet)
        self.assertNotIn('threadStatuses', packet)
        self.ipc.unwatch.assert_called_once_with(T)

    def test_new_client_after_last_close_gets_a_fresh_lifecycle(self):
        first = self.open()
        first.close()
        second = self.open()
        self.assertIsNot(first.owner, second.owner)
        second.subscribe({'type':'subscribe', 'threadIds':[T], 'subscription':'new'})
        self.assertEqual(second.update()[0]['threadStatuses'][T]['state'], 'idle')
