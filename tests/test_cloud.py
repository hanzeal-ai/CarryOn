"""End-to-end gateway -> outbound WS -> real API/Bridge, with no native desktop."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from carryon.bridge import Bridge
from carryon.cloud import CloudConnector
from carryon.cloud_wire import endpoint
from carryon.gateway import Gateway
from carryon.store import Journal

T='11111111-1111-4111-8111-111111111111'

class Catalog:
    def get(self,tid):return {'id':tid,'created_at':time.time()}
    def list(self,*_):return [{'id':T,'title':'fixture','cwd':'/tmp'}]
    def queued(self,tid):return []

class IPC:
    sends=0
    def __init__(self,_):self.connected=False
    def connect(self):self.connected=True
    def close(self):self.connected=False
    def current(self,tid):return {'id':tid,'threadRuntimeStatus':{'type':'idle'},'requests':[], 'turns':[]}
    def snapshot(self,tid):return 'owner',self.current(tid)
    sidebar_snapshot=snapshot
    def watch(self,tid):pass
    def unwatch(self,tid):pass
    def start(self,tid,prompt,owner,mid,before_send):
        def send():type(self).sends+=1
        before_send(send)
        return {'id':'turn'}

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.journal=Journal(self.path/'jobs.sqlite');IPC.sends=0
        self.bridge=Bridge('unused',Catalog(),self.journal,IPC)
        self.gateway=Gateway(('127.0.0.1',0),{'devices':{
            'device-a':{'deviceToken':'d'*40,'apiToken':'a'*40},
            'device-b':{'deviceToken':'e'*40,'apiToken':'b'*40}}})
        self.worker=threading.Thread(target=self.gateway.serve_forever,daemon=True);self.worker.start()
        self.connector=CloudConnector(self.bridge,config={'enabled':False},binding_id=None)
        self.config={'enabled':True,'deviceId':'device-a','token':'d'*40,
            'url':f'ws://127.0.0.1:{self.gateway.server_port}/device','devLocal':True,'control':False}
    def tearDown(self):
        self.connector.stop();self.bridge.disable()
        if self.bridge.realtime:
            for worker in self.bridge.realtime.workers:worker.join(3)
        self.gateway.shutdown();self.gateway.server_close();self.worker.join(3)
        self.journal.conn.close();self.temp.cleanup()
    def wait(self,predicate):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        self.fail('timed out')
    def configure_connector(self, config):
        self.connector.stop()
        self.connector = CloudConnector(self.bridge, config=config, binding_id=self.connector.binding_id)
        self.connector.start()
    def connect(self,control=False):
        CloudTests.configure_connector(self,{**self.config,'control':control})
        self.wait(lambda:self.connector.status()['connected'])
    def call(self,method,suffix,body=None,token='a'*40,device='device-a'):
        c=http.client.HTTPConnection('127.0.0.1',self.gateway.server_port,timeout=4)
        c.request(method,'/v1/devices/'+device+suffix,body=json.dumps(body) if body is not None else None,
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        response=c.getresponse();result=(response.status,json.loads(response.read()));c.close();return result
    def request(self,method,path,body=None):return self.call('POST','/request',{'method':method,'path':path,'body':body})
    def test_public_health_has_no_credentials(self):
        c=http.client.HTTPConnection('127.0.0.1',self.gateway.server_port,timeout=4)
        c.request('GET','/healthz');response=c.getresponse()
        self.assertEqual(response.status,200)
        result=json.loads(response.read());c.close()
        self.assertEqual(set(result),{'service','version','release'})
        self.assertEqual(result['service'],'carryon-gateway')
    def test_read_scope_device_isolation_and_closed_bridge(self):
        self.connect()
        self.assertEqual(self.call('GET','',device='device-b')[0],401)
        self.assertEqual(self.request('GET','/api/threads')[0],403)
        self.assertEqual(self.request('POST','/api/bridge',{'enabled':True})[0],403)
        self.bridge.enable()
        self.assertEqual(self.request('GET','/api/threads')[1]['threads'][0]['id'],T)
        self.assertEqual(self.request('POST','/api/threads/'+T+'/messages',{'requestId':'request-cloud','prompt':'hello'})[0],403)
        self.assertEqual(IPC.sends,0)
        self.assertNotIn('token',self.connector.status())
    def test_control_uses_local_idempotency_and_revocation(self):
        self.connect(control=True);self.bridge.enable()
        body={'requestId':'request-cloud','prompt':'hello'}
        self.assertEqual(self.request('POST','/api/threads/'+T+'/messages',body)[0],202)
        self.wait(lambda:IPC.sends==1)
        self.assertEqual(self.request('POST','/api/threads/'+T+'/messages',body)[0],202)
        self.assertEqual(IPC.sends,1)
        self.assertEqual(self.request('POST','/api/service/stop',{})[0],403)
        self.bridge.disable()
        self.assertEqual(self.request('POST','/api/threads/'+T+'/messages',{**body,'requestId':'request-next'})[0],403)
        self.assertEqual(IPC.sends,1)
    def test_multiple_streams_and_disconnect_invalidate_history(self):
        self.connect();self.bridge.enable()
        code,created=self.call('POST','/streams',{'threadId':T,'threadIds':[T]})
        self.assertEqual(code,200);sid=created['streamId']
        self.wait(lambda:self.gateway.devices['device-a'].streams[sid]['revision']>0)
        code,result=self.call('GET','/streams/'+sid+'?after=-1')
        self.assertEqual(result['body']['history']['thread']['id'],T)
        self.assertEqual(result['body']['threadStatuses'][T]['state'],'idle')
        self.assertEqual(self.call('DELETE','/streams/'+sid)[0],200)
        self.assertEqual(self.call('GET','/streams/'+sid)[0],404)
        self.configure_connector({'enabled':False})
        self.wait(lambda:'device-a' not in self.gateway.devices)
        self.assertEqual(self.request('GET','/api/threads')[0],503)
    def test_bad_subscription_does_not_drop_authenticated_device(self):
        self.connect();self.bridge.enable()
        self.assertEqual(self.call('POST','/streams',{'threadIds':['invalid']})[0],400)
        self.assertEqual(self.request('GET','/api/status')[0],200)
    def test_tls_and_credential_policy(self):
        for url in ('http://cloud.test/device','ws://cloud.test/device','wss://user:pass@cloud.test/device','wss://cloud.test/device?token=x'):
            with self.assertRaises(ValueError):endpoint(url,True)
        endpoint('wss://cloud.test/device')
        with self.assertRaises(ValueError):endpoint('ws://127.0.0.1/device')
        from carryon.cloud_manager import CloudManager
        manager=CloudManager(self.bridge,self.path)
        manager.configure(self.config,start=False)
        self.assertEqual((self.path/'cloud.json').stat().st_mode&0o777,0o600)
    def test_invalid_device_credential_returns_no_data(self):
        self.configure_connector({**self.config,'token':'wrong'*8})
        self.wait(lambda:self.connector.status()['error'] is not None)
        self.assertFalse(self.connector.status()['connected'])
        self.assertEqual(self.call('GET','')[1]['online'],False)

    def test_slow_requests_do_not_block_ping_and_inflight_is_bounded(self):
        from queue import Queue
        from unittest.mock import Mock
        from types import SimpleNamespace
        incoming=Queue();sent=Queue();release=threading.Event();entered=threading.Event()
        def receive():
            message=incoming.get(timeout=3)
            if message is None:raise EOFError()
            return message
        ws=SimpleNamespace(receive=receive,send=sent.put)
        def execute(message,control,connection_cancel):
            entered.set();release.wait(2)
            return {'type':'response','id':message['id'],'status':200,'body':{}}
        self.connector.execute=Mock(side_effect=execute)
        cancel=threading.Event();connection_cancel=threading.Event()
        def run():
            try:self.connector.session(ws,{},cancel,connection_cancel)
            except EOFError:pass
        worker=threading.Thread(target=run);worker.start()
        try:
            for i in range(5):incoming.put({'type':'request','id':str(i)})
            self.assertTrue(entered.wait(1))
            incoming.put({'type':'ping','id':'heartbeat'})
            responses=[sent.get(timeout=1),sent.get(timeout=1)]
            self.assertTrue(any(r.get('status')==503 for r in responses))
            self.assertTrue(any(r.get('type')=='pong' for r in responses))
            self.assertLessEqual(self.connector.execute.call_count,4)
            incoming.put(None);worker.join(1)
            self.assertTrue(connection_cancel.is_set())
            release.set()
        finally:
            release.set()
            if worker.is_alive():incoming.put(None)
            worker.join(3)

    def test_unchanged_native_snapshot_does_not_retransmit_history(self):
        self.connect();self.bridge.enable()
        native=self.bridge.ipc.current(T)
        self.bridge.ipc.current=lambda tid:native
        code,created=self.call('POST','/streams',{'threadId':T,'threadIds':[]})
        self.assertEqual(code,200);sid=created['streamId']
        device=self.gateway.devices['device-a']
        self.wait(lambda:device.streams[sid]['revision']>0)
        before=device.streams[sid]['revision']
        for _ in range(20):self.bridge.notify();time.sleep(.005)
        time.sleep(.2)
        self.assertEqual(device.streams[sid]['revision'],before)
        self.bridge.ipc.current=lambda tid:{**native,'title':'changed'}
        self.bridge.notify()
        self.wait(lambda:device.streams[sid]['revision']>before)
