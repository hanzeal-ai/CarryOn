import json
import hashlib
import tempfile
import threading
import time
import unittest
from pathlib import Path

from carryon.bridge import Bridge, BridgeError, snapshot_history
from carryon.ipc import IPCError
from carryon.store import Journal

THREAD = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"


class Catalog:
    def get(self, thread_id):
        return {"id": thread_id, "title": "test", "created_at": time.time()}


class FakeIPC:
    sends = 0
    runtime = "idle"
    error = None
    def __init__(self, _):
        self.connected = False
    def connect(self):
        self.connected = True
    def close(self):
        self.connected = False
    def snapshot(self, _):
        return "owner", {"threadRuntimeStatus": {"type": self.runtime}, "requests": []}
    def start(self, thread_id, prompt, owner, message_id, before_send):
        def write():
            type(self).sends += 1
        before_send(write)
        if self.error:
            raise self.error
        return {"id": "turn-1"}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.temp.name) / "jobs.sqlite")
        FakeIPC.sends = 0
        FakeIPC.runtime = "idle"
        FakeIPC.error = None
        self.bridge = Bridge("socket", Catalog(), self.journal, FakeIPC)
    def tearDown(self):
        self.bridge.disable()
        self.journal.conn.close()
        self.temp.cleanup()
    def await_job(self, request_id):
        for _ in range(100):
            job = self.journal.get(request_id)
            if job["state"] not in ("preparing", "dispatching"):
                return job
            time.sleep(.01)
        self.fail("job timed out")
    def test_disabled_rejects_control(self):
        with self.assertRaises(BridgeError):
            self.bridge.submit("message", "request-123", "hello", THREAD)
        self.assertEqual(FakeIPC.sends, 0)
    def test_duplicate_and_conflict(self):
        self.bridge.enable()
        self.bridge.submit("message", "request-123", "hello", THREAD)
        self.await_job("request-123")
        self.bridge.submit("message", "request-123", "hello", THREAD)
        self.assertEqual(FakeIPC.sends, 1)
        with self.assertRaises(BridgeError):
            self.bridge.submit("message", "request-123", "changed", THREAD)
    def test_native_active_state_blocks_send(self):
        self.bridge.enable()
        FakeIPC.runtime = "active"
        self.bridge.submit("message", "request-123", "hello", THREAD)
        self.assertEqual(self.await_job("request-123")["state"], "failed")
        self.assertEqual(FakeIPC.sends, 0)
    def test_timeout_never_replays_and_blocks_next(self):
        self.bridge.enable()
        FakeIPC.error = IPCError("timeout", uncertain=True)
        self.bridge.submit("message", "request-123", "hello", THREAD)
        self.assertEqual(self.await_job("request-123")["state"], "uncertain")
        with self.assertRaises(BridgeError):
            self.bridge.submit("message", "request-456", "hello again", THREAD)
        self.bridge.submit("message", "request-123", "hello", THREAD)
        self.assertEqual(FakeIPC.sends, 1)
    def test_disable_during_preparation_prevents_dispatch(self):
        reached, proceed = threading.Event(), threading.Event()
        class Slow(FakeIPC):
            def snapshot(self, thread_id):
                reached.set(); proceed.wait(2)
                return super().snapshot(thread_id)
        self.bridge.ipc_factory = Slow
        self.bridge.enable()
        self.bridge.submit("message", "request-123", "hello", THREAD)
        self.assertTrue(reached.wait(1))
        self.bridge.disable(); proceed.set()
        self.assertEqual(self.await_job("request-123")["state"], "failed")
        self.assertEqual(FakeIPC.sends, 0)
    def test_controller_required(self):
        self.bridge.enable()
        with self.assertRaises(BridgeError):
            self.bridge.submit("create", "request-123", "hello")
    def test_unconfirmed_creation_is_not_success(self):
        self.bridge.enable()
        self.journal.insert({"id": "request-123", "fingerprint": "f", "kind": "create",
            "threadId": THREAD, "created": time.time(), "state": "accepted", "turnId": "turn-1",
            "expectedTitle": "test"})
        self.bridge.turn_evidence = lambda *_: {"status": "completed", "text": "done"}
        self.assertEqual(self.bridge.refresh_job("request-123")["state"], "uncertain")
    def test_restart_marks_dispatch_uncertain(self):
        self.journal.insert({"id": "request-123", "fingerprint": "f", "kind": "message",
            "threadId": THREAD, "created": time.time(), "state": "dispatching"})
        other = Journal(Path(self.temp.name) / "jobs.sqlite")
        try:
            self.assertEqual(other.get("request-123")["state"], "uncertain")
        finally:
            other.conn.close()
    def test_creation_requires_native_matching_tool_evidence(self):
        self.bridge.enable()
        fingerprint = hashlib.sha256(json.dumps(["create", THREAD, "hello"], ensure_ascii=False).encode()).hexdigest()
        self.journal.insert({"id":"request-123", "fingerprint":fingerprint, "kind":"create",
            "threadId":THREAD, "created":time.time(), "state":"accepted", "turnId":"turn-1",
            "expectedTitle":"title that the app may normalize"})
        call = {"status":"completed", "arguments":{"target":{"type":"projectless"},
            "prompt":"hello", "title":"title that the app may normalize"},
            "result":{"content":[{"type":"text","text":json.dumps({"threadId":CHILD,"hostId":"local"})}]}}
        turn = {"status":"completed", "text":"", "createCalls":[call]}
        self.bridge.turn_evidence = lambda *_: turn
        call["arguments"]["prompt"] = "wrong prompt"
        self.assertEqual(self.bridge.refresh_job("request-123")["state"], "uncertain")
        call["arguments"]["prompt"] = "hello"
        result = self.bridge.refresh_job("request-123")
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["createdThreadId"], CHILD)
        self.assertEqual(FakeIPC.sends, 0)  # Reconciliation is read-only.
    def test_fabricated_final_marker_is_not_creation_evidence(self):
        self.bridge.enable()
        self.journal.insert({"id":"request-123", "fingerprint":"f", "kind":"create",
            "threadId":THREAD, "created":time.time(), "state":"accepted", "turnId":"turn-1",
            "expectedTitle":"test"})
        self.bridge.turn_evidence = lambda *_: {"status":"completed",
            "text":'CARRYON_RESULT '+json.dumps({"requestId":"request-123","threadId":CHILD})}
        self.assertEqual(self.bridge.refresh_job("request-123")["state"], "uncertain")
    def test_canonical_history_uses_native_order_and_final(self):
        turn = {"turnId": "t", "status": "completed", "params": {"input": [{"type":"text","text":"hello"}]},
                "items": [{"type":"agentMessage","id":"m","text":"你好","phase":"final_answer"}]}
        state = {"id": THREAD, "turnHistory": {"kind":"canonical", "history": {
            "isComplete": True, "entitiesByKey":{"k":turn}, "islands":[{"entries":[{"value":"k"}]}]}}}
        result = snapshot_history(state)
        self.assertEqual([m["text"] for m in result["messages"]], ["hello", "你好"])
        self.assertEqual(result["turns"]["t"]["text"], "你好")

    def test_acknowledgement_survives_inflight_reconciliation(self):
        self.bridge.enable()
        self.journal.insert({"id":"request-race", "fingerprint":"f", "kind":"create",
            "threadId":THREAD, "created":time.time(), "state":"uncertain", "turnId":"t"})
        entered, resume = threading.Event(), threading.Event()
        results, errors = [], []
        def evidence(*_):
            entered.set()
            if not resume.wait(3): raise RuntimeError('test timed out')
            return {'status': 'completed', 'createCalls': []}
        def refresh():
            try: results.append(self.bridge.refresh_job('request-race'))
            except Exception as exc: errors.append(exc)
        self.bridge.turn_evidence = evidence
        worker = threading.Thread(target=refresh)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.bridge.resolve('request-race')['state'], 'acknowledged')
        finally:
            resume.set(); worker.join(3)
        self.assertFalse(errors)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]['state'], 'acknowledged')
        self.assertEqual(self.journal.get('request-race')['state'], 'acknowledged')
        self.bridge.submit('message', 'request-next', 'hello', THREAD)
        self.assertEqual(self.await_job('request-next')['state'], 'accepted')

    def test_stale_evidence_cannot_replace_newer_job(self):
        self.journal.insert({'id':'request-cas', 'fingerprint':'f', 'kind':'message',
            'threadId':THREAD, 'created':time.time(), 'state':'accepted'})
        old = self.journal.get('request-cas')
        self.journal.update('request-cas', state='completed')
        result = self.journal.update('request-cas', expected=old, state='failed')
        self.assertEqual(result['state'], 'completed')
        before = self.bridge.event_revision
        self.assertEqual(self.journal.update('request-cas', state='completed'), result)
        self.assertEqual(self.bridge.event_revision, before)

    def test_approval_flags_block_controller_and_delivery(self):
        class Waiting(FakeIPC):
            def snapshot(self, tid):
                owner, state = super().snapshot(tid)
                state['threadRuntimeStatus']['activeFlags'] = ['waitingOnApproval']
                return owner, state
        self.bridge.ipc_factory = Waiting
        self.bridge.enable()
        with self.assertRaises(BridgeError): self.bridge.select_controller(THREAD)
        self.bridge.submit('message', 'request-wait', 'hello', THREAD)
        self.assertEqual(self.await_job('request-wait')['state'], 'failed')
        self.assertEqual(FakeIPC.sends, 0)

    def test_job_evidence_does_not_build_display_history(self):
        from unittest.mock import Mock
        self.bridge.enable()
        native={'id':THREAD,'turns':[{'turnId':str(i),'status':'completed','items':[]} for i in range(4000)]}
        self.bridge.ipc.current=lambda tid:native
        self.bridge.history=Mock(side_effect=AssertionError('display history must not be projected'))
        self.journal.insert({'id':'request-evidence','fingerprint':'f','kind':'message',
            'threadId':THREAD,'created':time.time(),'state':'accepted','turnId':'3999'})
        self.assertEqual(self.bridge.refresh_job('request-evidence')['state'],'completed')
        self.bridge.history.assert_not_called()
        native={'id':THREAD,'turnHistory':{'kind':'canonical','history':{'entitiesByKey':{'key':{'turnId':'canonical','status':'interrupted','items':[]}},'islands':[{'entries':[{'value':'key'}]}]}}}
        self.assertEqual(self.bridge.turn_evidence(THREAD,'canonical')['status'],'interrupted')
        self.assertIsNone(self.bridge.turn_evidence(THREAD,'missing'))


if __name__ == "__main__":
    unittest.main()
