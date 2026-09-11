"""Real browser-style socket through console, gateway and outbound device bridge."""
import base64
import os
import socket
import time
from types import SimpleNamespace

import test_console
from test_cloud import T
from connectnow.pairing import redeem
from connectnow.websocket import WebSocket


class ConsoleSocketTests(test_console.ConsoleTests):
    def wait_for(self, predicate):
        end = time.monotonic() + 4
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.01)
        self.fail('timed out')

    def connect_device(self):
        self.login()
        code = self.call('POST', '/console/pairing', {'deviceId': 'my-mac'})[1]['code']
        self.connector.configure(redeem(self.url, code, dev_local=True))
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
        self.assertEqual(packet['type'], 'update')
        self.assertEqual(packet['subscription'], 'test')
        return ws, packet

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
        from connectnow.events import Events
        from connectnow.workspace import Workspace
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
