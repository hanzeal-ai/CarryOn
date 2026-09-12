import base64
import io
import json
import os
import socket
import struct
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from carryon.ipc import DesktopIPC
from carryon.patches import apply_patches
from carryon.server import Server, Handler
from carryon.websocket import WebSocket

THREAD = '01a08062-8ff1-75c1-a426-299b4c0a31f7'


class PatchTests(unittest.TestCase):
    def test_immer_arrays_and_atomic_failure(self):
        original = {'items': [{'text': 'a'}]}
        updated = apply_patches(original, [
            {'op':'replace', 'path':['items',0,'text'], 'value':'ab'},
            {'op':'add', 'path':['items',1], 'value':{'text':'c'}},
            {'op':'remove', 'path':['items',0]}])
        self.assertEqual(updated, {'items':[{'text':'c'}]})
        self.assertEqual(original, {'items':[{'text':'a'}]})
        with self.assertRaises((ValueError, IndexError)):
            apply_patches(original, [{'op':'remove','path':['items',8]}])
        self.assertEqual(original['items'][0]['text'], 'a')

    def test_owner_revision_and_resync(self):
        ipc = DesktopIPC('unused')
        ipc.following[THREAD] = 'owner'
        ipc._resync = Mock()
        ipc.on_change = Mock()
        message = {'version':11,'sourceClientId':'owner'}
        params = {'hostId':'local'}
        ipc._change(message, params, THREAD, {'type':'snapshot','revision':1,
            'conversationState':{'id':THREAD,'text':'a'}})
        ipc._change(message, params, THREAD, {'type':'patches','baseRevision':1,'revision':2,
            'patches':[{'op':'replace','path':['text'],'value':'ab'}]})
        self.assertEqual(ipc.current(THREAD)['text'], 'ab')
        ipc._change({**message,'sourceClientId':'other'}, params, THREAD,
                    {'type':'snapshot','revision':3,'conversationState':{'id':THREAD,'text':'bad'}})
        self.assertEqual(ipc.current(THREAD)['text'], 'ab')
        ipc._change(message, params, THREAD, {'type':'patches','baseRevision':4,'revision':5,'patches':[]})
        self.assertIsNone(ipc.current(THREAD))
        for _ in range(100):
            if ipc._resync.called: break
            time.sleep(.001)
        ipc._resync.assert_called_once_with(THREAD)


class FakeIPC:
    def __init__(self): self.states = {}
    def watch(self, tid): pass
    def unwatch(self, tid): pass
    def current(self, tid): return self.states.get(tid)
    def snapshot(self, tid):
        from carryon.ipc import IPCError
        raise IPCError('no-client-found')
    sidebar_snapshot = snapshot


class FakeBridge:
    from carryon.bridge import Bridge
    open_stream = Bridge.open_stream
    def __init__(self):
        self.events = threading.Condition()
        self.event_revision = 0
        self.lock = threading.RLock()
        self.enabled = True
        self.realtime = None
        self.text = 'a'
        self.ipc = FakeIPC()
        self.journal = SimpleNamespace(list=lambda limit=None: [])
    def notify(self):
        with self.events:
            self.event_revision += 1
            self.events.notify_all()
    def status(self): return {'enabled':self.enabled,'controllerId':None}
    def require(self): return self.ipc, 1
    def check_generation(self, ipc, generation):
        if not self.enabled: raise ValueError('disabled')
    def history(self, tid): return {'thread':{'id':tid},'messages':[{'text':self.text}]}
    def side_chats(self, tid):
        return {'chats':[{'id':THREAD,'parentId':tid,'title':'side','state':'running','label':'执行中'}], 'scanning':False}
    def side_history(self, parent, tid):
        return {'parentId':parent,'thread':{'id':tid},'messages':[{'text':'side '+self.text}]}


class WSTests(unittest.TestCase):
    def setUp(self):
        self.server = Server(('127.0.0.1',0),Handler)
        self.server.token = 'a'*43
        self.server.bridge = FakeBridge()
        self.server.allowed_hosts = {f'127.0.0.1:{self.server.server_port}'}
        self.worker = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()
        self.clients = []
    def tearDown(self):
        for client in self.clients: client.close()
        self.server.shutdown();self.server.server_close();self.worker.join()
    def connect(self, origin=None):
        client = socket.create_connection(self.server.server_address,timeout=2)
        self.clients.append(client)
        key = base64.b64encode(os.urandom(16)).decode()
        host = next(iter(self.server.allowed_hosts))
        client.sendall((f'GET /api/stream HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: {origin or "http://"+host}\r\n\r\n').encode())
        headers = b''
        while not headers.endswith(b'\r\n\r\n'): headers += client.recv(1)
        return client, headers
    def send(self, client, message):
        data = json.dumps(message).encode();mask=os.urandom(4)
        header=bytes([129,128|len(data)]) if len(data)<126 else bytes([129,254])+struct.pack('!H',len(data))
        client.sendall(header+mask+bytes(v^mask[i%4] for i,v in enumerate(data)))
    def receive(self, client):
        def exact(n):
            b=b''
            while len(b)<n:
                c=client.recv(n-len(b))
                if not c: raise EOFError()
                b+=c
            return b
        a,b=exact(2);size=b&127
        if size==126:size=struct.unpack('!H',exact(2))[0]
        if size==127:size=struct.unpack('!Q',exact(8))[0]
        data=exact(size)
        return a&15, json.loads(data) if a&15==1 else data
    def until(self, client, predicate):
        for _ in range(10):
            op,data=self.receive(client)
            if op==1 and predicate(data):return data
        self.fail('Missing update')
    def test_authenticated_event_push_switch_and_revocation(self):
        c,h=self.connect();self.assertIn(b'101',h)
        self.send(c,{'type':'auth','token':self.server.token})
        self.until(c,lambda d:d['type']=='update')
        self.send(c,{'type':'subscribe','threadId':THREAD,'subscription':'one'})
        first=self.until(c,lambda d:d.get('subscription')=='one')
        self.assertEqual(first['history']['messages'][0]['text'],'a')
        start=time.monotonic();self.server.bridge.text='streamed';self.server.bridge.notify()
        update=self.until(c,lambda d:d.get('history',{}).get('messages')==[{'text':'streamed'}])
        self.assertLess(time.monotonic()-start,1)
        self.send(c,{'type':'subscribe','threadId':None,'subscription':'two'})
        self.assertNotIn('history',self.until(c,lambda d:d.get('subscription')=='two'))
        self.server.bridge.enabled=False;self.server.bridge.notify()
        revoked=self.until(c,lambda d:not d['status']['enabled'])
        self.assertNotIn('history',revoked)
    def test_wrong_token_no_data(self):
        c,h=self.connect();self.send(c,{'type':'auth','token':'wrong'})
        op,data=self.receive(c);self.assertEqual(op,8);self.assertEqual(struct.unpack('!H',data[:2])[0],1008)
    def test_sidebar_push_without_selecting_conversation(self):
        self.server.bridge.ipc.states[THREAD]={'threadRuntimeStatus':{'type':'active'}}
        c,h=self.connect();self.send(c,{'type':'auth','token':self.server.token})
        self.send(c,{'type':'subscribe','threadId':None,'threadIds':[THREAD],'subscription':'sidebar'})
        first=self.until(c,lambda d:d.get('subscription')=='sidebar')
        self.assertNotIn('history',first)
        self.assertEqual(first['threadStatuses'][THREAD]['state'],'running')
        self.server.bridge.ipc.states[THREAD]={'threadRuntimeStatus':{'type':'idle'}}
        start=time.monotonic();self.server.bridge.notify()
        update=self.until(c,lambda d:d.get('threadStatuses',{}).get(THREAD,{}).get('state')=='idle')
        self.assertLess(time.monotonic()-start,1)
        self.send(c,{'type':'subscribe','threadId':None,'threadIds':[],'subscription':'removed'})
        self.assertEqual(self.until(c,lambda d:d.get('subscription')=='removed')['threadStatuses'],{})
    def test_missing_owner_is_not_idle(self):
        c,h=self.connect();self.send(c,{'type':'auth','token':self.server.token})
        self.send(c,{'type':'subscribe','threadId':None,'threadIds':[THREAD],'subscription':'missing'})
        result=self.until(c,lambda d:d.get('threadStatuses',{}).get(THREAD,{}).get('state')=='notLoaded')
        self.assertEqual(result['threadStatuses'][THREAD]['label'],'未加载')
    def test_disabled_does_not_send_sidebar_statuses(self):
        self.server.bridge.enabled=False
        c,h=self.connect();self.send(c,{'type':'auth','token':self.server.token})
        self.send(c,{'type':'subscribe','threadId':None,'threadIds':[THREAD],'subscription':'off'})
        self.assertNotIn('threadStatuses',self.until(c,lambda d:d.get('subscription')=='off'))
    def test_sidebar_subscription_is_bounded(self):
        c,h=self.connect();self.send(c,{'type':'auth','token':self.server.token})
        self.until(c,lambda d:d['type']=='update')
        self.send(c,{'type':'subscribe','threadId':None,'threadIds':[THREAD]*101,'subscription':'too-many'})
        with self.assertRaises(EOFError):self.receive(c)
    def test_side_chat_stream_is_separate_and_closes_with_drawer(self):
        c,h=self.connect();self.send(c,{'type':'auth','token':self.server.token})
        self.send(c,{'type':'subscribe','threadId':THREAD,'includeSideChats':True,'sideThreadId':THREAD,'subscription':'side'})
        packet=self.until(c,lambda d:d.get('subscription')=='side')
        self.assertEqual(packet['history']['messages'][0]['text'],'a')
        self.assertEqual(packet['sideHistory']['messages'][0]['text'],'side a')
        self.server.bridge.text='updated';self.server.bridge.notify()
        update=self.until(c,lambda d:d.get('sideHistory',{}).get('messages')==[{'text':'side updated'}])
        self.assertEqual(update['sideThreadId'],THREAD)
        self.send(c,{'type':'subscribe','threadId':THREAD,'subscription':'closed'})
        packet=self.until(c,lambda d:d.get('subscription')=='closed')
        self.assertNotIn('sideHistory',packet);self.assertNotIn('sideChats',packet)
    def test_cross_origin_rejected_before_upgrade(self):
        c,h=self.connect('https://evil.example');self.assertIn(b'403',h)
    def test_coordination_events_push_flags_and_queue(self):
        from carryon.events import Events
        bridge=self.server.bridge;ipc=bridge.ipc
        ipc.lock=threading.RLock();ipc.following={THREAD:'owner'};ipc.on_change=bridge.notify
        ipc.events=Events(ipc)
        ipc.states[THREAD]={'threadRuntimeStatus':{'type':'active'}}
        previous=bridge.history
        bridge.history=lambda tid:{**previous(tid),'queue':ipc.events.queues.get(tid,[])}
        c,h=self.connect();self.send(c,{'type':'auth','token':self.server.token})
        self.send(c,{'type':'subscribe','threadId':THREAD,'threadIds':[THREAD],'subscription':'events'})
        self.until(c,lambda d:d.get('subscription')=='events')
        def event(method,version,**params):
            ipc.events.handle({'method':method,'version':version,'sourceClientId':'owner',
                'params':{'hostId':'local','conversationId':THREAD,**params}})
        event('thread-read-state-changed',2,hasUnreadTurn=True)
        self.until(c,lambda d:d.get('threadFlags',{}).get(THREAD,{}).get('hasUnreadTurn') is True)
        event('thread-archived',2)
        self.until(c,lambda d:d.get('catalogRevision')==1 and d['threadFlags'][THREAD]['archived'])
        event('thread-unarchived',1)
        self.until(c,lambda d:d.get('catalogRevision')==2 and not d['threadFlags'][THREAD]['archived'])
        event('thread-queued-followups-changed',1,messages=[{'id':'q1','text':'queued','context':{}}])
        self.until(c,lambda d:d.get('history',{}).get('queue')==[{'id':'q1','text':'queued','context':{}}])
    def test_unmasked_frame_rejected(self):
        c,h=self.connect();c.sendall(b'\x81\x02{}');self.assertEqual(c.recv(1),b'')
    def test_no_records_before_authentication(self):
        c,h=self.connect();c.settimeout(.1)
        with self.assertRaises(socket.timeout):c.recv(1)

    def test_heartbeat_continues_while_history_is_loading(self):
        from unittest.mock import patch
        from carryon import websocket
        entered=threading.Event();release=threading.Event()
        original=self.server.bridge.history
        def history(tid):
            entered.set();release.wait(2);return original(tid)
        self.server.bridge.history=history
        with patch.object(websocket,'HEARTBEAT_INTERVAL',.03):
            c,_=self.connect();self.send(c,{'type':'auth','token':self.server.token})
            self.send(c,{'type':'subscribe','threadId':THREAD,'subscription':'slow'})
            try:
                self.assertTrue(entered.wait(1))
                pings=0
                while pings < 2:
                    opcode,data=self.receive(c)
                    if opcode==9:pings+=1
                    elif opcode==1:self.assertNotEqual(data.get('subscription'),'slow')
            finally:
                release.set()


if __name__ == '__main__': unittest.main()
