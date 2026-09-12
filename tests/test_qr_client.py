import hashlib
import http.client
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from carryon.console import ConsoleServer
from carryon.console_auth import password_record
from carryon.qr_client import exchange, terminal_qr


class QRClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.cert=Path(cls.temp.name)/'cert.pem';cls.key=Path(cls.temp.name)/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(cls.key),
                        '-out',str(cls.cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True)
        cls.account=password_record('owner','owner-password-123')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.state=tempfile.TemporaryDirectory()
        self.server=ConsoleServer(('127.0.0.1',0),{'publicUrl':'https://localhost','account':self.account,'devices':{}},self.state.name)
        self.url=f'https://localhost:{self.server.server_port}'
        self.server.origin=self.server.public_url=self.url
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(self.cert,self.key)
        self.server.socket=context.wrap_socket(self.server.socket,server_side=True)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.trust=ssl.create_default_context(cafile=str(self.cert))
        self.patch=patch('carryon.qr_client.tls_context',return_value=self.trust);self.patch.start()

    def tearDown(self):
        self.patch.stop();self.server.shutdown();self.server.server_close();self.worker.join(3);self.state.cleanup()

    def phone(self,route,body=None,cookie=''):
        conn=http.client.HTTPSConnection('localhost',self.server.server_port,context=self.trust,timeout=5)
        conn.request('GET' if body is None else 'POST','/console/'+route,json.dumps(body) if body is not None else None,
                     {'Origin':self.url,'Content-Type':'application/json','Cookie':cookie})
        response=conn.getresponse();value=json.loads(response.read());cookie=response.getheader('Set-Cookie')
        status=response.status;conn.close();return status,value,cookie

    def invitation(self):
        return exchange(self.url,{'action':'create','username':'owner','password':'owner-password-123'})

    def claim(self,invite):
        key,secret=urlsplit(invite['url']).fragment.removeprefix('carryon-login=').split('.')
        body={'id':key,'secret':secret,'claim':'a'*36}
        status,data,_=self.phone('qr/claim',body);self.assertEqual(status,200)
        return body,data['verification']

    def test_native_owner_confirms_phone_and_close_preserves_phone_session(self):
        invite=self.invitation();owner=hashlib.sha256(invite['session'].encode()).hexdigest()
        self.assertLessEqual(self.server.sessions[owner]-time.monotonic(),300)
        claim,code=self.claim(invite)
        self.assertEqual(exchange(self.url,{**invite,'action':'status'})['verification'],code)
        with self.assertRaises(ValueError):exchange(self.url,{**invite,'action':'approve','verification':'000000' if code!='000000' else '111111'})
        self.assertEqual(self.phone('qr/poll',claim)[1]['state'],'scanned')
        exchange(self.url,{**invite,'action':'approve','verification':code})
        status,data,cookie=self.phone('qr/poll',claim);self.assertEqual(status,200);self.assertTrue(data['authenticated'])
        self.assertEqual(exchange(self.url,{**invite,'action':'status'})['state'],'redeemed')
        exchange(self.url,{**invite,'action':'close'})
        self.assertNotIn(owner,self.server.sessions)
        self.assertEqual(self.phone('session',cookie=cookie)[0],200)

    def test_reject_close_expire_and_other_owner_cannot_approve(self):
        for action in ('reject','close','expire'):
            invite=self.invitation();claim,code=self.claim(invite)
            other=self.invitation()
            with self.assertRaises(ValueError):exchange(self.url,{**invite,'session':other['session'],'action':'approve','verification':code})
            exchange(self.url,{**other,'action':'close'})
            if action=='expire':self.server.auth.qrs[invite['id']]['expires']=time.monotonic()-1
            else:exchange(self.url,{**invite,'action':action})
            status,data,cookie=self.phone('qr/poll',claim)
            self.assertFalse(data.get('authenticated'));self.assertIsNone(cookie)
            if action=='reject':self.assertEqual(data['state'],'rejected')
            else:self.assertEqual(status,403)

    def test_invalid_password_and_changed_public_url_never_return_invitation(self):
        with self.assertRaises(ValueError):exchange(self.url,{'action':'create','username':'owner','password':'wrong'})
        self.server.public_url='https://other.invalid'
        with self.assertRaisesRegex(ValueError,'二维码地址'):self.invitation()
        self.assertFalse(self.server.sessions)

    @unittest.skipUnless(__import__('sys').platform=='darwin','macOS JavaScriptCore')
    def test_terminal_encoder_uses_shipped_library_and_has_quiet_zone(self):
        invite=self.invitation();qr=terminal_qr(invite['url']);rows=qr.splitlines()
        self.assertGreater(len(rows),20);self.assertEqual(len(set(map(len,rows))),1)
        self.assertTrue(all(c=='█' for c in rows[0]+rows[1]))
        self.assertTrue(all(row.startswith('████') and row.endswith('████') for row in rows))
        self.assertNotIn(invite['session'],qr)
        exchange(self.url,{**invite,'action':'close'})
