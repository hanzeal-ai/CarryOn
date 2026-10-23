"""Invitation WS transitions using isolated accounts and real local sockets."""
import json
import time
import unittest
from urllib.parse import urlsplit
import test_console
import test_console_socket

class ConfirmationSocketTests(unittest.TestCase):
    setUp=test_console.ConsoleTests.setUp
    tearDown=test_console.ConsoleTests.tearDown
    call=test_console.ConsoleTests.call
    login=test_console.ConsoleTests.login
    socket=test_console_socket.ConsoleSocketTests.socket

    def create(self):
        self.login()
        status,qr,_=self.call('POST','/console/qr/create',{})
        self.assertEqual(status,200)
        identifier,secret=urlsplit(qr['url']).fragment.removeprefix('carryon-login=').split('.')
        return {'id':identifier,'secret':secret,'claim':'a'*36}

    def watch(self,kind,data,cookie=True):
        status,ws=self.socket('/console/confirmation/ws',cookie=cookie)
        self.assertEqual(status,101)
        ws.send({'type':'subscribe','kind':kind,'invitation':data})
        return ws

    def test_claim_approval_redemption_and_reconnect(self):
        data=self.create();owner=self.watch('qr-owner',{'id':data['id']})
        self.assertEqual(owner.receive()['body']['state'],'waiting')
        status,claim,_=self.call('POST','/console/qr/claim',data)
        self.assertEqual(status,200)
        self.assertEqual(owner.receive()['body']['state'],'scanned')
        scanner=self.watch('qr-claim',data,False)
        self.assertEqual(scanner.receive()['body'],{'state':'scanned'})
        self.assertEqual(self.call('POST','/console/qr/approve',{**data,'verification':claim['verification']})[0],200)
        packet=scanner.receive();self.assertEqual(packet['body'],{'state':'approved'})
        self.assertNotIn(data['claim'],json.dumps(packet))
        again=self.watch('qr-claim',data,False)
        self.assertEqual(again.receive()['body'],{'state':'approved'})
        self.assertTrue(self.call('POST','/console/qr/poll',data)[1]['authenticated'])
        self.assertEqual(scanner.receive()['body'],{'state':'redeemed'})

    def test_wrong_claim_owner_origin_and_query(self):
        data=self.create();self.call('POST','/console/qr/claim',data)
        for kind,inv,cookie in [('qr-claim',{**data,'claim':'b'*36},False),('qr-owner',data,False)]:
            self.assertTrue(self.watch(kind,inv,cookie).receive()['terminal'])
        for path,options,expected in [('/console/confirmation/ws',{'origin':False},403),('/console/confirmation/ws?secret=x',{},400)]:
            self.assertEqual(self.socket(path,**options)[0],expected)

    def test_expiry_and_logout_wake_subscribers(self):
        for action in ('expiry','logout'):
            data=self.create();self.call('POST','/console/qr/claim',data)
            if action=='expiry':self.server.auth.qrs[data['id']]['expires']=time.monotonic()+.1
            scanner=self.watch('qr-claim',data,False)
            self.assertEqual(scanner.receive()['type'],'confirmation')
            if action=='logout':self.call('POST','/console/logout',{})
            self.assertTrue(scanner.receive()['terminal'])

    def test_binding_confirmation_and_reconnect_never_expose_credentials(self):
        import hashlib
        self.login();secret='s'*43
        invitation={'id':'b'*32,'secret':secret}
        entry={'name':'isolated','permissions':['view'],'state':'accepted','account':'owner',
               'targetAccount':'owner','expires':time.time()+30,'scan':hashlib.sha256(secret.encode()).hexdigest(),
               'poll':hashlib.sha256(b'p'*43).hexdigest()}
        with self.server.binding_invites.lock:
            self.server.binding_invites.entries[invitation['id']]=entry
            self.server.binding_invites.save()
        ws=self.watch('binding',invitation)
        self.assertEqual(ws.receive()['body']['state'],'accepted')
        with self.server.binding_invites.lock:
            entry['state']='bound';self.server.binding_invites.save()
        packet=ws.receive();self.assertEqual(packet['body']['state'],'bound')
        self.assertNotIn(secret,json.dumps(packet));self.assertNotIn('poll',json.dumps(packet))
        self.assertEqual(self.watch('binding',invitation).receive()['body']['state'],'bound')
        self.assertTrue(self.watch('binding',{**invitation,'secret':'z'*43}).receive()['terminal'])
