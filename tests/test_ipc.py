import json
import socket
import struct
import threading
import unittest
from unittest.mock import patch, Mock
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError


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
        ipc.snapshots[tid]=(1,{'id':tid,'hasUnreadTurn':True})
        ipc.snapshot=lambda target:('owner',ipc.current(target))
        data=json.dumps({'type':'broadcast','method':'thread-read-state-changed','version':3,
            'sourceClientId':'owner','params':{'hostId':'local','conversationId':tid,'hasUnreadTurn':True,'context':{}}}).encode()
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


class WakeSnapshotTests(unittest.TestCase):
    @patch('carryon.desktop_ipc.ipc.sys.platform', 'darwin')
    @patch('carryon.desktop_ipc.ipc.subprocess.run')
    def test_opens_existing_thread_and_reads_native_idle_state(self, run):
        tid='11111111-1111-4111-8111-111111111111'
        ipc=DesktopIPC('unused')
        ipc.owner=Mock(return_value='owner')
        state={'id':tid,'threadRuntimeStatus':{'type':'idle'}}
        ipc._snapshot=Mock(return_value=('owner',state))
        guard=Mock()
        self.assertEqual(ipc.wake_snapshot(tid,before_open=guard),('owner',state))
        run.assert_called_once_with(['open','-g','codex://threads/'+tid],check=True,capture_output=True,timeout=3)
        self.assertGreaterEqual(guard.call_count,2)
        ipc._snapshot.assert_called_once_with(tid,'owner')

    @patch('carryon.desktop_ipc.ipc.sys.platform', 'darwin')
    @patch('carryon.desktop_ipc.ipc.subprocess.run')
    def test_revoked_authorization_or_invalid_id_never_opens(self, run):
        ipc=DesktopIPC('unused')
        denied=Mock(side_effect=PermissionError('revoked'))
        with self.assertRaises(PermissionError):
            ipc.wake_snapshot('11111111-1111-4111-8111-111111111111',before_open=denied)
        with self.assertRaises(ValueError):ipc.wake_snapshot('bad/id',before_open=Mock())
        run.assert_not_called()

    @patch('carryon.desktop_ipc.ipc.sys.platform', 'darwin')
    @patch('carryon.desktop_ipc.ipc.subprocess.run', side_effect=OSError('unavailable'))
    def test_open_failure_remains_failure(self, run):
        ipc=DesktopIPC('unused')
        with self.assertRaises(IPCError):
            ipc.wake_snapshot('11111111-1111-4111-8111-111111111111',before_open=Mock())

class ReceiptErrorTests(unittest.TestCase):
    def test_explicit_refusal_is_failed_but_router_timeout_is_uncertain(self):
        for error, uncertain in [('permission denied', False), ('no-client-found', False), ('request-timeout', True), ('thread-follower-start-turn-timeout', True)]:
            ipc = DesktopIPC('unused')
            def respond(message):
                waiter = ipc.pending[message['requestId']]
                waiter['response'] = {'resultType': 'error', 'error': error}
                waiter['event'].set()
            ipc._write = respond
            with self.assertRaises(IPCError) as caught:
                ipc.request('thread-follower-start-turn', {})
            self.assertEqual(caught.exception.uncertain, uncertain)
            self.assertEqual(ipc.pending, {})

class OwnerWireTests(unittest.TestCase):
    def test_owner_uncertain_response_survives_socket_wire(self):
        left, right = socket.socketpair()
        follower, owner = DesktopIPC('unused'), DesktopIPC('unused')
        follower.sock, owner.sock = left, right
        owner.request_handler = Mock()
        owner.request_handler.can_handle.return_value = True
        owner.request_handler.handle.side_effect = IPCError('app-server reply lost', uncertain=True)
        readers = [threading.Thread(target=ipc._reader, args=(sock,), daemon=True)
                   for ipc, sock in ((follower, left), (owner, right))]
        for reader in readers: reader.start()
        try:
            with self.assertRaises(IPCError) as caught:
                follower.request('thread-follower-start-turn', {}, version=2, timeout_ms=500)
            self.assertTrue(caught.exception.uncertain)
            owner.request_handler.handle.assert_called_once()
        finally:
            follower.close(); owner.close()
            for reader in readers: reader.join(1)

class IncomingResponseLifetimeTests(unittest.TestCase):
    def test_request_stays_in_flight_until_response_write_finishes_or_fails(self):
        for fail in (False, True):
            with self.subTest(write_fails=fail):
                ipc = DesktopIPC('unused'); ipc.request_handler = Mock()
                entered, proceed, done = threading.Event(), threading.Event(), threading.Event()
                def write(_message):
                    entered.set(); proceed.wait(2)
                    if fail: raise IPCError('socket gone')
                ipc._write = write
                release = ipc.request_slots.release
                ipc.request_slots = Mock(wraps=ipc.request_slots)
                def finish(): release(); done.set()
                ipc.request_slots.release.side_effect = finish
                ipc._incoming_request({'requestId': 'one', 'method': 'test'})
                try:
                    self.assertTrue(entered.wait(1))
                    self.assertEqual(ipc.requests_in_flight, 1)
                finally: proceed.set()
                self.assertTrue(done.wait(1))
                self.assertEqual(ipc.requests_in_flight, 0)


class RouterDiscoveryDeadlineTests(unittest.TestCase):
    def test_slow_discovery_returns_definite_missing_owner_without_resend(self):
        # The native router discovery deadline is independent of timeoutMs.
        # A late no-client-found must arrive before our local request expires.
        left, right = socket.socketpair()
        ipc = DesktopIPC('unused'); ipc.sock = left
        reader = threading.Thread(target=ipc._reader, args=(left,), daemon=True); reader.start()
        requests = []
        def router():
            size = struct.unpack('<I', DesktopIPC._exact(right, 4))[0]
            request = json.loads(DesktopIPC._exact(right, size)); requests.append(request)
            threading.Event().wait(3.1)
            payload = json.dumps({'type': 'response', 'requestId': request['requestId'],
                                  'resultType': 'error', 'error': 'no-client-found'}).encode()
            right.sendall(struct.pack('<I', len(payload)) + payload)
        worker = threading.Thread(target=router); worker.start()
        try:
            with self.assertRaisesRegex(IPCError, '^no-client-found$') as caught:
                ipc.owner('11111111-1111-4111-8111-111111111111', timeout_ms=20)
            self.assertFalse(caught.exception.uncertain)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]['timeoutMs'], 20)
        finally:
            worker.join(5); ipc.close(); right.close(); reader.join(1)
