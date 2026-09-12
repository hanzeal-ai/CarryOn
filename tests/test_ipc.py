import json
import socket
import struct
import threading
import unittest
from connectnow.ipc import DesktopIPC, IPCError


class ProtocolTests(unittest.TestCase):
    def test_fragmented_response_and_disconnect(self):
        client, peer = socket.socketpair()
        ipc = DesktopIPC('unused')
        ipc.sock = client
        reader = threading.Thread(target=ipc._reader, args=(client,), daemon=True)
        reader.start()
        def serve():
            size = struct.unpack('<I', DesktopIPC._exact(peer,4))[0]
            request = json.loads(DesktopIPC._exact(peer,size))
            payload = json.dumps({'type':'response','requestId':request['requestId'],
                'resultType':'success','result':{'clientId':'test'}}).encode()
            frame = struct.pack('<I',len(payload))+payload
            for byte in frame:
                peer.sendall(bytes([byte]))
        server = threading.Thread(target=serve)
        server.start()
        try:
            result = ipc.request('initialize',{'clientType':'test'})
            self.assertEqual(result['result']['clientId'],'test')
            self.assertEqual(ipc.pending,{})
        finally:
            server.join(1);peer.close();reader.join(1);ipc.close()
        self.assertFalse(ipc.connected)
    def test_oversized_frame_disconnects(self):
        client, peer = socket.socketpair()
        ipc = DesktopIPC('unused');ipc.sock=client
        reader=threading.Thread(target=ipc._reader,args=(client,),daemon=True);reader.start()
        peer.sendall(struct.pack('<I',ipc.MAX_FRAME+1))
        reader.join(1);peer.close()
        self.assertFalse(ipc.connected)
    def test_native_broadcast_frame_reaches_coordination_handler(self):
        tid='11111111-1111-4111-8111-111111111111'
        client,peer=socket.socketpair();ipc=DesktopIPC('unused');ipc.sock=client
        ipc.following[tid]='owner';changed=threading.Event();ipc.on_change=changed.set
        reader=threading.Thread(target=ipc._reader,args=(client,),daemon=True);reader.start()
        data=json.dumps({'type':'broadcast','method':'thread-read-state-changed','version':2,
            'sourceClientId':'owner','params':{'hostId':'local','conversationId':tid,'hasUnreadTurn':True}}).encode()
        try:
            peer.sendall(struct.pack('<I',len(data))+data)
            self.assertTrue(changed.wait(1))
            self.assertTrue(ipc.events.flags[tid]['hasUnreadTurn'])
        finally:peer.close();reader.join(1);ipc.close()


class SnapshotConcurrencyTests(unittest.TestCase):
    def test_slow_thread_does_not_block_another_thread(self):
        ipc = DesktopIPC('unused')
        entered, release, fast = threading.Event(), threading.Event(), threading.Event()
        def load(tid, owner=None):
            if tid == 'slow':
                entered.set(); release.wait(2)
            else:
                fast.set()
            return 'owner', {'id':tid}
        ipc._snapshot = load
        slow = threading.Thread(target=ipc.snapshot, args=('slow',))
        quick = threading.Thread(target=ipc.snapshot, args=('fast',))
        slow.start()
        try:
            self.assertTrue(entered.wait(1)); quick.start()
            self.assertTrue(fast.wait(.5), 'another thread waited behind complete history')
        finally:
            release.set(); slow.join(2); quick.join(2)

    def test_sidebar_reuses_snapshot_after_waiting_for_same_thread(self):
        ipc = DesktopIPC('unused')
        ipc.owner = lambda *args, **kwargs: 'owner'
        entered, release = threading.Event(), threading.Event()
        calls = []
        def load(tid, owner=None):
            calls.append(tid); entered.set(); release.wait(2)
            with ipc.lock:
                ipc.following[tid] = 'owner'
                ipc.snapshots[tid] = (1, {'id':tid})
            return 'owner', {'id':tid}
        ipc._snapshot = load
        first = threading.Thread(target=ipc.snapshot, args=('same',))
        second = threading.Thread(target=ipc.sidebar_snapshot, args=('same',))
        first.start()
        try:
            self.assertTrue(entered.wait(1)); second.start(); release.set()
            first.join(2); second.join(2)
            self.assertEqual(calls, ['same'])
        finally:
            release.set(); first.join(2); second.join(2)
