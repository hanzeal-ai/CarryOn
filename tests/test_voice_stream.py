"""Native event wakeup and bounded cursor delivery, no microphone/account access."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_native_voice as fixture
from carryon.routes.realtime import Subscription
T=fixture.T

class VoiceStreamTests(unittest.TestCase):
    setUp=fixture.NativeVoiceTests.setUp
    rpc=fixture.NativeVoiceTests.rpc
    start=fixture.NativeVoiceTests.start

    def test_event_wakes_subscription_ack_and_reconnect_cursor(self):
        identifier=self.start()['result']['voiceId']
        self.runtime.on_change=self.bridge.notify
        self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':identifier}})
        owner=SimpleNamespace(bridge=self.bridge,sync_watches=lambda:None,load_event=threading.Event())
        subscription=Subscription(owner)
        selection={'type':'subscribe','subscription':'one','threadId':T,'voiceId':identifier,'voiceAfter':0}
        subscription.subscribe(selection)
        revision=self.bridge.event_revision
        self.runtime._event({'method':'thread/realtime/transcript/delta','params':{'threadId':T,'delta':'hello'}})
        self.assertGreater(self.bridge.event_revision,revision)
        with patch.object(self.bridge,'history',return_value={}):
            first=subscription.update()[0]['voice']
            self.assertEqual(first['events'][0]['delta'],'hello')
            self.assertEqual(first['sequence'],1)
            subscription.ack_voice({'subscription':'wrong','voiceId':identifier,'after':1})
            self.assertEqual(len(subscription.update()[0]['voice']['events']),1)
            subscription.ack_voice({'subscription':'one','voiceId':identifier,'after':1})
            self.assertEqual(subscription.update()[0]['voice']['events'],[])
            subscription.subscribe({**selection,'subscription':'reconnected','voiceAfter':1})
            self.runtime._event({'method':'thread/realtime/transcript/delta','params':{'threadId':T,'delta':' world'}})
            self.assertEqual([e['sequence'] for e in subscription.update()[0]['voice']['events']],[2])
            subscription.subscribe({**selection,'voiceId':'22222222-2222-4222-8222-222222222222'})
            packet=subscription.update()[0];self.assertIn('voiceError',packet);self.assertNotIn('voice',packet)
        for value in (True,-1,'1',None):
            with self.assertRaises(ValueError):subscription.ack_voice({'after':value})

import test_console
import test_console_socket

class CloudVoiceStreamTests(unittest.TestCase):
    setUp=test_console.ConsoleTests.setUp
    tearDown=test_console.ConsoleTests.tearDown
    call=test_console.ConsoleTests.call
    login=test_console.ConsoleTests.login
    configure_device=test_console.ConsoleTests.configure_device
    device_config=test_console.ConsoleTests.device_config
    socket=test_console_socket.ConsoleSocketTests.socket
    wait_for=test_console_socket.ConsoleSocketTests.wait_for

    def connect(self,control=True):
        self.login();self.configure_device({**self.device_config(),'control':control});self.bridge.enable()
        self.wait_for(lambda:self.connector.status()['connected'])
        status,ws=self.socket();self.assertEqual(status,101);return ws

    def subscribe(self,ws):
        from test_cloud import T as thread
        ws.send({'type':'subscribe','subscription':'voice','threadId':thread,'voiceId':T})
        return self.packet(ws)

    def packet(self,ws):
        packet=ws.receive()
        while packet['type']=='ping':ws.send({'type':'pong'});packet=ws.receive()
        return packet

    def test_view_only_and_local_read_only_cannot_subscribe_voice(self):
        ws=self.connect()
        self.server.config['devices']['my-mac']['members']['owner']=['view']
        packet=self.subscribe(ws);self.assertEqual(packet['type'],'error');self.assertEqual(packet['status'],401)
        self.assertFalse(self.server.devices['my-mac'].streams)

    def test_local_read_only_cannot_subscribe_voice(self):
        ws=self.connect(False);packet=self.subscribe(ws)
        self.assertEqual(packet['type'],'error');self.assertEqual(packet['status'],400)

    def test_voice_ack_keeps_stream_and_invalid_cursor_does_not_disconnect_device(self):
        voice={'voice':{'id':T,'state':'active'},'sequence':1,'events':[{'sequence':1,'type':'transcript/delta','delta':'private'}],'dropped':False}
        with patch('carryon.codex_protocol.realtime_voice.read',return_value=voice):
            ws=self.connect();packet=self.subscribe(ws);self.assertEqual(packet['body']['voice'],voice)
            device=self.server.devices['my-mac'];streams=set(device.streams)
            ws.send({'type':'voice-ack','subscription':'voice','voiceId':T,'after':1})
            self.wait_for(lambda:any(s.selection.get('voiceAfter')==1 for s in self.bridge.realtime.sessions))
            self.assertEqual(set(device.streams),streams)
            ws.send({'type':'voice-ack','subscription':'voice','voiceId':T,'after':'bad'})
            self.assertEqual(self.packet(ws)['type'],'error')
            self.assertFalse(device.closed);self.assertTrue(self.connector.status()['connected'])

    def test_revoked_send_permission_prevents_next_voice_delivery(self):
        voice={'voice':{'id':T,'state':'active'},'sequence':1,'events':[],'dropped':False}
        with patch('carryon.codex_protocol.realtime_voice.read',return_value=voice):
            ws=self.connect();self.assertEqual(self.subscribe(ws)['type'],'update')
            self.server.config['devices']['my-mac']['members']['owner']=['view']
            voice['sequence']=2;self.bridge.notify()
            packet=self.packet(ws);self.assertEqual(packet['type'],'error');self.assertEqual(packet['status'],401)
