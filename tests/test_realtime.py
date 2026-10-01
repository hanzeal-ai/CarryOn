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

from carryon.desktop_ipc.ipc import DesktopIPC
from carryon.desktop_ipc.patches import apply_patches
from carryon.server import Server, Handler
from carryon.routes.websocket import WebSocket

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
        from carryon.desktop_ipc.ipc import IPCError
        raise IPCError('no-client-found')
    sidebar_snapshot = snapshot


class FakeBridge:
    from carryon.sessions.bridge import Bridge
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
    def status(self): return {'enabled':self.enabled}
    def require(self): return self.ipc, 1
    def check_generation(self, ipc, generation):
        if not self.enabled: raise ValueError('disabled')
    def history(self, tid): return {'thread':{'id':tid},'timeline':[{'text':self.text}]}
    def side_chats(self, tid):
        return {'chats':[{'id':THREAD,'parentId':tid,'title':'side','state':'running','label':'执行中'}], 'scanning':False}
    def side_history(self, parent, tid):
        return {'parentId':parent,'thread':{'id':tid},'timeline':[{'text':'side '+self.text}]}


class StatusSchedulingTests(unittest.TestCase):
    def setUp(self):
        from carryon.routes.realtime import Realtime, Subscription
        self.bridge=FakeBridge();self.realtime=Realtime(self.bridge)
        self.session=Subscription(self.realtime);self.realtime.sessions.add(self.session)
        self.ids=[f'00000000-0000-4000-8000-{n:012d}' for n in range(47)]
        self.realtime.watched={tid:self.bridge.ipc for tid in self.ids}

    def test_slow_router_misses_cannot_starve_tail_running_conversation(self):
        from unittest.mock import patch
        now=0;pending={};attempted=set();active=self.ids[-1]
        # Real router misses occupy each slot for ten seconds. Drive the actual
        # scheduler over virtual time so its thirty-second retry cooldown applies.
        with patch('carryon.routes.realtime.time.monotonic',side_effect=lambda:now):
            for now in range(601):
                for tid,finish in list(pending.items()):
                    if finish<=now:
                        del pending[tid]
                        if tid==active:
                            self.bridge.ipc.states[tid]={'threadRuntimeStatus':{'type':'active'}}
                        else:
                            self.realtime.unavailable[tid]=(self.bridge.ipc,now,{'state':'notLoaded','label':'未加载'})
                for tid in self.realtime._load_candidates(pending):
                    pending[tid]=now+10;attempted.add(tid)
                self.assertLessEqual(len(pending),4)
                if self.bridge.ipc.current(active):break
        self.assertEqual(attempted,set(self.ids))
        self.assertLessEqual(now,120)
        self.assertEqual(self.realtime.thread_status(active,self.bridge.ipc,self.bridge.ipc.current(active))['state'],'running')

    def test_visible_and_selected_threads_precede_background_with_background_progress(self):
        self.session.selection.update(threadId=self.ids[-1],threadIds=self.ids[-5:-1])
        picked=self.realtime._load_candidates({})
        self.assertEqual(picked[0],self.ids[-1])
        self.assertEqual(sum(tid in self.ids[-5:] for tid in picked),3)
        self.assertEqual(len(picked),4)
        self.assertEqual(self.realtime._load_candidates(dict.fromkeys(picked)),[])

    def test_visible_retries_do_not_repeat_ahead_of_unchecked_visible_rows(self):
        from unittest.mock import patch
        self.session.selection['threadIds']=self.ids
        with patch('carryon.routes.realtime.time.monotonic',return_value=100):
            first=self.realtime._load_candidates({})
            for tid in first:self.realtime.unavailable[tid]=(self.bridge.ipc,0,{'state':'notLoaded','label':'未加载'})
            self.assertTrue(set(first).isdisjoint(self.realtime._load_candidates({})))

    def test_refresh_bypasses_miss_cooldown_but_preserves_live_snapshot(self):
        now=time.monotonic();missing,live=self.ids[-2:]
        self.realtime.unavailable[missing]=(self.bridge.ipc,now,{'state':'notLoaded','label':'未加载'})
        state={'threadRuntimeStatus':{'type':'active'}};self.bridge.ipc.states[live]=state
        self.realtime.refresh_statuses([missing,live])
        self.assertNotIn(missing,self.realtime.unavailable)
        self.assertEqual(self.realtime._load_candidates({})[0],missing)
        self.assertIs(self.bridge.ipc.current(live),state)

    def test_reconnect_does_not_reuse_previous_ipc_failure(self):
        tid=self.ids[0]
        self.realtime.unavailable[tid]=(self.bridge.ipc,time.monotonic(),{'state':'notLoaded','label':'未加载'})
        new=FakeIPC();self.bridge.ipc=new
        self.assertEqual(self.realtime.thread_status(tid,new,new.current(tid))['state'],'loading')
        new.states[tid]={'threadRuntimeStatus':{'type':'active'}}
        self.assertEqual(self.realtime.thread_status(tid,new,new.current(tid))['state'],'running')

    def test_visible_thread_recovers_when_busy_background_workers_finish(self):
        from carryon.desktop_ipc.ipc import IPCError
        active=self.ids[-1];release=threading.Event();busy=threading.Event()
        entered=[];lock=threading.Lock()
        self.bridge.workspace=SimpleNamespace(thread_ids=lambda:set(self.ids),invalidate_status=self.bridge.notify,revision=0)
        def snapshot(tid):
            if tid==active:
                self.bridge.ipc.states[tid]={'threadRuntimeStatus':{'type':'active'}}
                return 'owner',self.bridge.ipc.states[tid]
            with lock:
                entered.append(tid)
                if len(entered)==4:busy.set()
            release.wait(2)
            raise IPCError('no-client-found')
        self.bridge.ipc.sidebar_snapshot=snapshot
        opened=self.realtime.open()
        try:
            self.assertTrue(busy.wait(1))
            self.session.subscribe({'type':'subscribe','threadId':None,'threadIds':[active],'subscription':'visible'})
            self.assertEqual(self.session.update()[0]['threadStatuses'][active]['state'],'loading')
            release.set()
            deadline=time.monotonic()+1
            while not self.bridge.ipc.current(active) and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(self.session.update()[0]['threadStatuses'][active]['state'],'running')
        finally:
            release.set();self.realtime.closed.set();self.realtime.load_event.set();self.bridge.notify()
            opened.close();self.session.close()
            for worker in self.realtime.workers:worker.join(2)
            self.assertTrue(all(not worker.is_alive() for worker in self.realtime.workers))


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
        self.assertEqual(first['history']['timeline'][0]['text'],'a')
        start=time.monotonic();self.server.bridge.text='streamed';self.server.bridge.notify()
        update=self.until(c,lambda d:d.get('history',{}).get('timeline')==[{'text':'streamed'}])
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
        self.assertEqual(packet['history']['timeline'][0]['text'],'a')
        self.assertEqual(packet['sideHistory']['timeline'][0]['text'],'side a')
        self.server.bridge.text='updated';self.server.bridge.notify()
        update=self.until(c,lambda d:d.get('sideHistory',{}).get('timeline')==[{'text':'side updated'}])
        self.assertEqual(update['sideThreadId'],THREAD)
        self.send(c,{'type':'subscribe','threadId':THREAD,'subscription':'closed'})
        packet=self.until(c,lambda d:d.get('subscription')=='closed')
        self.assertNotIn('sideHistory',packet);self.assertNotIn('sideChats',packet)
    def test_cross_origin_rejected_before_upgrade(self):
        c,h=self.connect('https://evil.example');self.assertIn(b'403',h)
    def test_coordination_events_push_flags_and_queue(self):
        from carryon.desktop_ipc.events import Events
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
        ipc.states[THREAD]['hasUnreadTurn']=True
        ipc.snapshot=lambda tid:('owner',ipc.current(tid))
        event('thread-read-state-changed',3,hasUnreadTurn=True,context={})
        self.until(c,lambda d:d.get('threadFlags',{}).get(THREAD,{}).get('hasUnreadTurn') is True)
        ipc.states[THREAD] = {**ipc.states[THREAD], 'hasUnreadTurn': False}
        bridge.notify()
        self.until(c,lambda d:d.get('threadFlags',{}).get(THREAD,{}).get('hasUnreadTurn') is False)
        event('thread-archived',2)
        self.until(c,lambda d:d.get('catalogRevision')==1 and d['threadFlags'][THREAD]['archived'])
        event('thread-unarchived',1)
        self.until(c,lambda d:d.get('catalogRevision')==2 and not d['threadFlags'][THREAD]['archived'])
        event('thread-queued-followups-changed',2,messages=[{'id':'q1','text':'queued','context':{}}])
        self.until(c,lambda d:d.get('history',{}).get('queue')==[{'id':'q1','text':'queued','context':{}}])
    def test_unmasked_frame_rejected(self):
        c,h=self.connect();c.sendall(b'\x81\x02{}');self.assertEqual(c.recv(1),b'')
    def test_no_records_before_authentication(self):
        c,h=self.connect();c.settimeout(.1)
        with self.assertRaises(socket.timeout):c.recv(1)

    def test_browser_probe_does_not_replace_subscription(self):
        c, _ = self.connect()
        self.send(c, {'type':'auth', 'token':self.server.token})
        self.send(c, {'type':'subscribe', 'threadId':THREAD, 'subscription':'probe'})
        self.until(c, lambda d:d.get('subscription') == 'probe')
        self.send(c, {'type':'ping'})
        self.assertEqual(self.until(c, lambda d:d.get('type') == 'pong'), {'type':'pong'})
        self.assertTrue(any(s.selection['subscription'] == 'probe' for s in self.server.bridge.realtime.sessions))

    def test_heartbeat_continues_while_history_is_loading(self):
        from unittest.mock import patch
        import carryon.routes.websocket as websocket
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
