"""Real browser-style socket through console, gateway and outbound device bridge."""
import base64
import os
import socket
import time
from types import SimpleNamespace

import test_console
from test_cloud import T
from carryon.websocket import WebSocket


class ConsoleSocketTests(test_console.ConsoleTests):
    def wait_for(self, predicate):
        end = time.monotonic() + 4
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.01)
        self.fail('timed out')

    def connect_device(self):
        self.login()
        self.configure_device(self.device_config())
        self.bridge.enable()
        self.wait_for(lambda: self.connector.status()['connected'])

    def socket(self, path='/console/devices/my-mac/ws', origin=True, cookie=True):
        sock = socket.create_connection(('127.0.0.1', self.server.server_port), timeout=4)
        self.addCleanup(sock.close)
        reader = sock.makefile('rb'); self.addCleanup(reader.close)
        headers = [f'GET {path} HTTP/1.1', f'Host: 127.0.0.1:{self.server.server_port}',
                   'Upgrade: websocket', 'Connection: Upgrade', 'Sec-WebSocket-Version: 13',
                   'Sec-WebSocket-Key: ' + base64.b64encode(os.urandom(16)).decode()]
        if origin: headers.append('Origin: ' + (self.url if origin is True else origin))
        if cookie: headers.append('Cookie: ' + self.cookie)
        sock.sendall(('\r\n'.join(headers) + '\r\n\r\n').encode())
        status = int(reader.readline().split()[1])
        while reader.readline() != b'\r\n': pass
        return status, WebSocket(SimpleNamespace(connection=sock, rfile=reader), client=True)

    def subscribed(self):
        status, ws = self.socket(); self.assertEqual(status, 101)
        ws.send({'type':'subscribe', 'subscription':'test', 'threadId':T, 'threadIds':[T]})
        packet = ws.receive()
        while packet['type'] == 'ping':
            ws.send({'type':'pong'}); packet = ws.receive()
        self.assertEqual(packet['type'], 'update')
        self.assertEqual(packet['subscription'], 'test')
        return ws, packet

    def test_continuous_updates_still_receive_heartbeats(self):
        import threading
        from unittest.mock import patch
        from carryon import console_socket
        with patch.object(console_socket, 'HEARTBEAT_INTERVAL', .05), patch.object(console_socket, 'READ_TIMEOUT', .25):
            self.connect_device()
            ws, _ = self.subscribed()
            device = self.server.devices['my-mac']
            sid = next(iter(device.streams))
            stop = threading.Event()
            def emit():
                while not stop.wait(.01):
                    device.receive({'type':'event', 'streamId':sid, 'body':{'type':'update'}})
            worker = threading.Thread(target=emit, daemon=True); worker.start()
            try:
                end = time.monotonic() + .8
                updates = pings = 0
                while time.monotonic() < end:
                    packet = ws.receive()
                    if packet['type'] == 'ping':
                        pings += 1; ws.send({'type':'pong'})
                    else:
                        updates += 1
                self.assertGreater(updates, 10)
                self.assertGreater(pings, 3)
                self.assertFalse(device.closed)
            finally:
                stop.set(); worker.join(1)
                ws.handler.connection.shutdown(socket.SHUT_RDWR)
                self.wait_for(lambda:not device.streams)

    def test_ws_auth_boundaries(self):
        self.login()
        for options, expected in [({'cookie':False},401), ({'origin':False},403),
                ({'origin':'https://evil.test'},403), ({'path':'/console/devices/missing/ws'},403),
                ({'path':'/console/devices/my-mac/ws?token=secret'},400)]:
            with self.subTest(options=options): self.assertEqual(self.socket(**options)[0],expected)

    def test_ws_push_logout_and_cleanup(self):
        self.connect_device()
        ws, initial = self.subscribed()
        self.assertEqual(initial['body']['history']['thread']['id'], T)
        device = self.server.devices['my-mac']
        self.wait_for(lambda: bool(device.streams))
        sid = next(iter(device.streams))
        # Inject a gateway event using the same receiver as the outbound device.
        started = time.monotonic()
        device.receive({'type':'event', 'streamId':sid, 'body':{'type':'update','marker':'changed'}})
        packet = ws.receive()
        while packet['body'].get('marker') != 'changed': packet = ws.receive()
        self.assertLess(time.monotonic()-started, 2)
        self.assertGreater(packet['revision'], initial['revision'])
        self.call('POST', '/console/logout', {})
        self.assertEqual(ws.receive()['status'], 401)
        self.wait_for(lambda: not self.server.console_streams and not device.streams)

    def test_ws_readonly_reconnect_and_invalid_selection(self):
        self.connect_device()
        ws, _ = self.subscribed()
        ws.send({'type':'compose', 'prompt':'must not execute'})
        packet = ws.receive()
        while packet['type'] == 'update': packet = ws.receive()
        self.assertEqual(packet['status'],400)
        self.wait_for(lambda:not self.server.console_streams)
        again, packet = self.subscribed()
        self.assertEqual(packet['body']['history']['thread']['id'],T)
        again.handler.connection.shutdown(socket.SHUT_RDWR)
        self.wait_for(lambda:not self.server.console_streams)
        status, invalid = self.socket()
        invalid.send({'type':'subscribe','subscription':'bad','threadIds':['invalid']})
        self.assertEqual(invalid.receive()['status'],400)
        self.wait_for(lambda:not self.server.console_streams)

    def test_ws_expiry_and_device_disconnect(self):
        self.connect_device()
        ws, _ = self.subscribed()
        with self.server.auth_lock:
            for key in self.server.sessions: self.server.sessions[key]=0
        packet=ws.receive()
        while packet['type']=='update': packet=ws.receive()
        self.assertEqual(packet['status'],401)
        self.wait_for(lambda:not self.server.console_streams)
        self.login()
        ws,_=self.subscribed()
        self.connector.stop()
        with self.assertRaises((EOFError,OSError)): ws.receive()
        self.wait_for(lambda:not self.server.console_streams)

    def test_ws_bridge_change_and_revocation(self):
        self.connect_device()
        ws, _ = self.subscribed()
        self.bridge.disable()
        packet = ws.receive()
        while packet['body'].get('status', {}).get('enabled') is not False:
            packet = ws.receive()
        self.assertFalse(packet['body']['status']['enabled'])
        self.server.revoke_device('my-mac')
        with self.assertRaises((EOFError, OSError)):
            while True: ws.receive()
        self.wait_for(lambda:not self.server.console_streams)

    def test_native_read_pushes_revision_and_clears_remote_projection(self):
        import threading
        from carryon.events import Events
        from carryon.workspace import Workspace
        from test_workspace import Native
        self.bridge.ipc_factory=Native
        self.connector.binding_id='read-sync-test'
        workspace=Workspace(self.bridge);self.bridge.workspace=workspace
        workspace.catalog_refresh()
        self.connect_device()
        ipc=self.bridge.ipc;ipc.lock=threading.RLock();ipc.following={};ipc.events=Events(ipc)
        state={'id':T,'threadRuntimeStatus':{'type':'idle'},'turns':[],
               'requests':[{'id':1,'method':'item/tool/requestUserInput','params':{'questions':[]}}]}
        ipc.states[T]=state;workspace.observe(state)
        route='/console/devices/my-mac/request'
        def unread():
            status,body,_=self.call('POST',route,{'method':'GET','path':'/api/projects'})
            self.assertEqual(status,200)
            return sum(project['unread'] for project in body['projects'])
        self.assertEqual(unread(),1)
        ws,initial=self.subscribed();before=initial['body']['workspaceRevision']
        ipc.events.handle({'method':'thread-read-state-changed','version':2,'sourceClientId':'desktop',
            'params':{'hostId':'local','conversationId':T,'hasUnreadTurn':False}})
        packet=ws.receive()
        while packet['body'].get('workspaceRevision',0)<=before: packet=ws.receive()
        self.assertEqual(unread(),0)
        self.assertTrue(next(t for t in workspace.projection('binding:read-sync-test')[1] if t['id']==T)['actionable'])

    def test_switch_subscription_on_same_socket_filters_old_stream(self):
        self.connect_device();ws,first=self.subscribed()
        self.assertTrue(first['resubscribe'])
        device=self.server.devices['my-mac'];old=next(iter(device.streams))
        ws.send({'type':'subscribe','subscription':'second','threadId':T,'threadIds':[]})
        while True:
            packet=ws.receive()
            if packet['type']=='ping':ws.send({'type':'pong'});continue
            if packet.get('subscription')=='second':break
        self.assertGreater(packet['revision'],first['revision'])
        self.assertEqual(packet['body']['subscription'],'second')
        self.assertNotIn(old,device.streams)
        self.assertEqual(len(device.streams),1)
        self.assertEqual(len(self.server.console_streams),1)
        for index in range(20):
            ws.send({'type':'subscribe','subscription':f'rapid-{index}','threadId':T,'threadIds':[]})
        while True:
            packet=ws.receive()
            if packet['type']=='ping':ws.send({'type':'pong'});continue
            self.assertEqual(packet['type'],'update')
            if packet.get('subscription')=='rapid-19':break
        self.assertEqual(len(device.streams),1)
        self.assertEqual(len(self.server.console_streams),1)

    def test_window_and_delta_roundtrip_through_device_gateway_console(self):
        from carryon.history_cache import NativeSnapshot
        from carryon.history_wire import HistoryWire
        from carryon.patches import apply_patches
        from test_performance_protocol import state
        self.connect_device()
        current=[state(1000)]
        self.bridge.ipc.current=lambda tid:current[0]
        _,ws=self.socket();ws.MAX_MESSAGE=32*1024*1024
        ws.send({'type':'subscribe','subscription':'window','threadId':T,'historyProtocol':1,'historyLimit':40})
        decoder=HistoryWire()
        def receive():
            while True:
                packet=ws.receive()
                if packet['type']=='ping':ws.send({'type':'pong'});continue
                self.assertEqual(packet['type'],'update')
                return packet['body']
        first=receive();full=decoder.decode(first)
        self.assertEqual(len(full['history']['timeline']),120)
        self.assertTrue(full['history']['historyWindow']['hasMore'])
        current[0]=NativeSnapshot(apply_patches(current[0],[{'op':'replace','path':['turns',999,'items',0,'text'],'value':'new streamed answer'}]))
        self.bridge.notify()
        delta=receive()
        self.assertIn('historyDelta',delta)
        changed=decoder.decode(delta)
        self.assertEqual(changed['history']['timeline'][-1]['text'],'new streamed answer')
        self.assertEqual(changed['history']['timeline'][-1]['text'],'new streamed answer')
        ws.send({'type':'subscribe','subscription':'earlier','threadId':T,'historyProtocol':1,'historyLimit':80})
        while True:
            packet=receive()
            if packet.get('subscription')=='earlier':break
        self.assertIn('history',packet)
        self.assertEqual(len(decoder.decode(packet)['history']['timeline']),240)
