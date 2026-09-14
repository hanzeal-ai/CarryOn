import tempfile
import time
import unittest
from pathlib import Path
from carryon.bridge import Bridge,BridgeError
from carryon.store import Journal
from carryon.remote_scope import scoped_dispatch
from test_operations import IPC,state,T

class Catalog:
    def get(self,tid):return {'id':tid}
    def queued(self,tid):return []

class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.journal=Journal(Path(self.temp.name)/'jobs.sqlite')
        self.bridge=Bridge('fake',Catalog(),self.journal,IPC);self.bridge.enable()
    def tearDown(self):
        self.bridge.disable();self.journal.conn.close();self.temp.cleanup()
    def wait(self,key):
        for _ in range(100):
            job=self.journal.get(key)
            if job['state'] not in ('preparing','dispatching'):return job
            time.sleep(.01)
        self.fail('dispatch timeout')
    def test_running_routes_to_native_steer_and_keeps_retry_identity(self):
        self.bridge.ipc.state=state('active')
        self.bridge.ipc.snapshot=lambda tid:('owner',self.bridge.ipc.state)
        self.bridge.ipc.current=lambda tid:self.bridge.ipc.state
        job=self.bridge.compose(T,'compose-running','hello');self.wait(job['id'])
        self.assertEqual(job['kind'],'operation:steer')
        self.assertEqual(len(self.bridge.ipc.calls),1)
        self.assertEqual(self.journal.get(job['id'])['clientMessageId'],self.bridge.ipc.calls[0][1]['clientUserMessageId'])
        self.bridge.ipc.state=state('idle')
        self.assertEqual(self.bridge.compose(T,'compose-running','hello')['id'],job['id'])
        self.assertEqual(len(self.bridge.ipc.calls),1)
        with self.assertRaises(BridgeError):self.bridge.compose(T,'compose-running','other')
    def test_waiting_uses_original_queue_and_readonly_is_rejected(self):
        pending=state('active');pending['requests']=[{'id':1,'method':'item/tool/requestUserInput','params':{'questions':[]}}]
        self.bridge.ipc.snapshot=lambda tid:('owner',pending);self.bridge.ipc.current=lambda tid:pending
        job=self.bridge.compose(T,'compose-waiting','hello');self.wait(job['id'])
        self.assertEqual(job['kind'],'operation:queue-add')
        self.assertEqual(self.bridge.ipc.calls[0][1]['state'][T][0]['text'],'hello')
        self.assertEqual(self.journal.get(job['id'])['clientMessageId'],self.bridge.ipc.calls[0][1]['state'][T][0]['id'])
        with self.assertRaises(BridgeError):scoped_dispatch(self.bridge,'POST',f'/api/threads/{T}/compose',{'requestId':'readonly-compose','prompt':'hello'},False,'readonly')
    def test_unknown_never_queues(self):
        self.bridge.ipc.snapshot=lambda tid:('owner',{'id':T})
        with self.assertRaises(BridgeError):self.bridge.compose(T,'compose-unknown','hello')
        self.assertEqual(self.journal.list(),[])

    def test_running_compose_reuses_its_fresh_snapshot_once(self):
        from unittest.mock import Mock
        native=state('active')
        self.bridge.ipc.snapshot=Mock(return_value=('owner',native))
        self.bridge.ipc.current=lambda tid:native
        job=self.bridge.compose(T,'compose-one-read','hello')
        self.assertEqual(self.wait(job['id'])['state'],'completed')
        self.assertEqual(self.bridge.ipc.snapshot.call_count,1)

    def test_prepared_snapshot_is_not_used_after_native_reset(self):
        from unittest.mock import Mock
        native=state('active')
        self.bridge.ipc.snapshot=Mock(return_value=('owner',native))
        self.bridge.ipc.current=lambda tid:None
        job=self.bridge.compose(T,'compose-reset-read','hello')
        self.assertEqual(self.wait(job['id'])['state'],'failed')
        self.assertEqual(self.bridge.ipc.calls,[])

    def test_running_and_waiting_images_preserve_native_inputs_and_retry(self):
        from test_images import PNG
        for waiting in (False, True):
            native = state('active')
            if waiting:
                native['requests'] = [{'id': 1, 'method': 'item/tool/requestUserInput'}]
            self.bridge.ipc.snapshot = lambda tid: ('owner', native)
            self.bridge.ipc.current = lambda tid: native
            key = 'compose-images-' + str(waiting)
            job = self.bridge.compose(T, key, '  ', [PNG])
            self.assertEqual(self.wait(key)['state'], 'completed')
            params = self.bridge.ipc.calls[-1][1]
            restored = params['state'][T][-1] if waiting else params['restoreMessage']
            self.assertEqual(restored['context']['imageAttachments'][0]['src'], PNG)
            if not waiting:
                self.assertEqual(params['input'], [{'type': 'image', 'url': PNG}])
            before = len(self.bridge.ipc.calls)
            self.bridge.compose(T, key, '  ', [PNG])
            self.assertEqual(len(self.bridge.ipc.calls), before)
            with self.assertRaises(BridgeError): self.bridge.compose(T, key, 'changed', [PNG])

    def test_invalid_running_image_is_rejected_before_dispatch(self):
        native = state('active')
        self.bridge.ipc.snapshot = lambda tid: ('owner', native)
        with self.assertRaises(ValueError): self.bridge.compose(T, 'bad-images-123', '', ['data:image/png;base64,xxx'])
        self.assertEqual(self.bridge.ipc.calls, [])
