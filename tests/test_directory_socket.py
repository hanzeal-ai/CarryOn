"""Real isolated sockets: account directory signals never carry device credentials."""
import json
import time
import unittest
from unittest.mock import patch

import test_console
import test_console_socket
from carryon.cloud.directory_socket import snapshot


class DirectorySocketTests(unittest.TestCase):
    setUp = test_console.ConsoleTests.setUp
    tearDown = test_console.ConsoleTests.tearDown
    call = test_console.ConsoleTests.call
    login = test_console.ConsoleTests.login
    socket = test_console_socket.ConsoleSocketTests.socket

    def connect(self):
        self.login()
        status, ws = self.socket('/console/events')
        self.assertEqual(status, 101)
        first = ws.receive()
        self.assertEqual(first['type'], 'directory-changed')
        self.assertEqual(set(first), {'type','revision'})
        return ws, first

    def test_auth_origin_and_query_boundaries(self):
        self.login()
        for options, expected in [({'cookie':False},401),({'origin':False},403),
                                  ({'origin':'https://evil.test'},403)]:
            status, _ = self.socket('/console/events',**options)
            self.assertEqual(status,expected)
        status,_ = self.socket('/console/events?token=not-a-credential')
        self.assertEqual(status,400)

    def test_mutations_invalidate_noop_does_not_and_logout_revokes(self):
        with patch('carryon.cloud.directory_socket.HEARTBEAT_INTERVAL',.1):
            ws, first = self.connect()
            self.server.notify_directory()
            packet=ws.receive()
            self.assertEqual(packet['type'],'ping')
            ws.send({'type':'pong'})
            self.server.save_devices({**self.server.config['devices'], 'my-mac':{
                **self.server.config['devices']['my-mac'], 'name':'Updated'}})
            packet=ws.receive()
            while packet['type']=='ping':ws.send({'type':'pong'});packet=ws.receive()
            self.assertEqual(packet['type'],'directory-changed')
            self.assertNotEqual(first['revision'],packet['revision'])
            self.assertNotIn('Updated',json.dumps(packet))
            self.assertEqual(self.call('POST','/console/logout',{})[0],200)
            packet=ws.receive()
            while packet['type']=='ping':ws.send({'type':'pong'});packet=ws.receive()
            self.assertEqual(packet['status'],401)

    def test_projection_is_view_scoped_and_device_removal_invalidates(self):
        ws, first=self.connect()
        key=next(iter(self.server.sessions))
        self.server.save_devices({**self.server.config['devices'],'hidden':{
            'deviceToken':'x'*40,'apiToken':'y'*40,'members':{},'name':'private'}})
        self.assertEqual(snapshot(self.server,key)[0],first['revision'])
        self.server.revoke_device('my-mac')
        packet=ws.receive()
        self.assertEqual(packet['type'],'directory-changed')
        self.assertNotEqual(packet['revision'],first['revision'])
        self.assertNotIn('my-mac',[d['id'] for d in self.server.session_info(key)['devices']])

    def test_binding_expiry_signals_without_periodic_reads(self):
        ws, first=self.connect()
        with self.server.binding_invites.lock:
            self.server.binding_invites.entries['test']={'name':'test','targetAccount':'owner',
                'state':'waiting','expires':time.time()+.3,'permissions':['view']}
            self.server.binding_invites.save()
        active=ws.receive()
        self.assertNotEqual(active['revision'],first['revision'])
        expired=ws.receive()
        self.assertEqual(expired['revision'],first['revision'])

    def test_reconnect_receives_current_snapshot_without_device_connection(self):
        ws, first=self.connect()
        status, second=self.socket('/console/events')
        self.assertEqual(status,101)
        self.assertEqual(second.receive(),first)
