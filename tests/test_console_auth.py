import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import urlsplit

from carryon.console import ConsoleServer
from carryon.console_auth import ConsoleAuth, SESSION_SECONDS, password_record


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.account = password_record('admin', 'a long password 123')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {'publicUrl':'http://127.0.0.1','account':self.account,'devices':{}}
        self.start()

    def start(self):
        self.server = ConsoleServer(('127.0.0.1',0), self.config, self.temp.name)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.server.origin=self.origin;self.server.public_url=self.origin
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)

    def tearDown(self):
        self.stop();self.temp.cleanup()

    def request(self, route, body=None, cookie='', origin=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Content-Type':'application/json','Cookie':cookie}
        if origin:headers['Origin']=self.origin
        conn.request('GET' if body is None else 'POST','/console/'+route,json.dumps(body) if body is not None else None,headers)
        response=conn.getresponse();data=json.loads(response.read());cookie=(response.getheader('Set-Cookie') or '').split(';')[0]
        status=response.status;conn.close();return status,data,cookie

    def login(self):
        status,_,cookie=self.request('login',{'username':'admin','password':'a long password 123'})
        self.assertEqual(status,200);return cookie

    def create(self, owner):
        status,data,_=self.request('qr/create',{},owner);self.assertEqual(status,200)
        key,secret=urlsplit(data['url']).fragment.removeprefix('carryon-login=').split('.')
        return {'id':key,'secret':secret,'claim':'a'*36}

    def test_password_hash_origin_failure_and_legacy_disabled(self):
        self.assertNotIn('a long password',json.dumps(self.account))
        self.assertNotEqual(password_record('admin','a long password 123')['hash'],self.account['hash'])
        self.assertEqual(self.request('login',{'username':'admin','password':'a long password 123'},origin=False)[0],403)
        for body in ({'username':'other','password':'a long password 123'}, {'username':'admin','password':'wrong'}, {'token':'x'*40}, {'username':[],'password':{}}, {'username':'admin','password':'x'*257}):
            self.assertEqual(self.request('login',body)[0],403)
        self.assertEqual(self.request('session',cookie=self.login())[0],200)
        self.assertEqual(self.request('session')[0],401)

    def test_rate_limit_is_global_not_spoofable_by_username(self):
        for i in range(10):self.assertEqual(self.request('login',{'username':str(i),'password':'wrong'})[0],403)
        status,data,_=self.request('login',{'username':'admin','password':'a long password 123'})
        self.assertEqual(status,403);self.assertIn('频繁',data['error'])
        self.server.auth.attempts=[time.monotonic()-61]
        self.login()

    def test_restart_logout_expiry_and_password_rotation(self):
        cookie=self.login()
        saved=json.loads((Path(self.temp.name)/'sessions.json').read_text())
        self.assertNotIn(cookie.split('=')[1],json.dumps(saved))
        self.assertTrue(all(time.time()+SESSION_SECONDS-10<v<=time.time()+SESSION_SECONDS for v in saved['sessions'].values()))
        self.stop();self.start();self.assertEqual(self.request('session',cookie=cookie)[0],200)
        self.assertEqual(self.request('logout',{},cookie)[0],200)
        self.stop();self.start();self.assertEqual(self.request('session',cookie=cookie)[0],401)
        cookie=self.login();self.stop()
        self.config['account']=password_record('admin','another long password')
        self.start();self.assertEqual(self.request('session',cookie=cookie)[0],401)

    def test_qr_requires_authenticated_owner_and_same_origin(self):
        self.assertEqual(self.request('qr/create',{})[0],401)
        owner=self.login();data=self.create(owner)
        self.assertEqual(self.request('qr/claim',data,origin=False)[0],403)
        self.assertEqual(self.request('qr/claim',{**data,'secret':'wrong'})[0],403)
        self.assertEqual(self.request('qr/poll',data)[0],403)
        self.assertEqual(self.request('qr/approve',data,owner)[0],400)
        _,claim,_=self.request('qr/claim',data)
        self.assertEqual(len(claim['verification']),6)
        self.assertEqual(self.request('qr/claim',data)[1],claim)
        self.assertEqual(self.request('qr/claim',{**data,'claim':'b'*36})[0],403)
        other=self.login()
        self.assertEqual(self.request('qr/status',data,other)[0],403)
        self.assertEqual(self.request('qr/approve',{**data,'verification':claim['verification']},other)[0],403)
        self.assertEqual(self.request('qr/approve',{**data,'verification':'wrong'},owner)[0],403)
        self.assertEqual(self.request('qr/poll',data)[1]['state'],'scanned')
        self.assertEqual(self.request('qr/approve',{**data,'verification':claim['verification']},owner)[0],200)
        self.assertEqual(self.request('qr/approve',{**data,'verification':claim['verification']},owner)[0],400)
        status,result,cookie=self.request('qr/poll',data)
        self.assertEqual(status,200);self.assertTrue(result['authenticated'])
        self.assertEqual(self.request('qr/poll',data)[2],cookie)
        self.assertEqual(self.request('session',cookie=cookie)[0],200)
        self.assertEqual(self.request('logout',{},cookie)[0],200)
        self.assertEqual(self.request('qr/poll',data)[0],403)

    def test_qr_reject_cancel_expire_and_owner_logout(self):
        owner=self.login()
        for action in ('reject','cancel','expire','logout'):
            data=self.create(owner);self.request('qr/claim',data)
            if action in ('reject','cancel'):self.assertEqual(self.request('qr/'+action,data,owner)[0],200)
            elif action=='expire':self.server.auth.qrs[data['id']]['expires']=time.monotonic()-1
            else:self.request('logout',{},owner)
            status,result,cookie=self.request('qr/poll',data)
            self.assertFalse(cookie)
            if action=='reject':self.assertEqual(result['state'],'rejected')
            else:self.assertEqual(status,403)

    def test_replacement_and_restart_invalidate_qr(self):
        owner=self.login();data=self.create(owner);self.create(owner)
        self.assertEqual(self.request('qr/claim',data)[0],403)
        data=self.create(owner);self.stop();self.start()
        self.assertEqual(self.request('qr/claim',data)[0],403)

    def test_account_change_removes_token_bypass_even_if_present(self):
        auth=ConsoleAuth({**self.config,'consoleToken':'x'*40},None)
        with self.assertRaises(PermissionError):auth.verify({'token':'x'*40})

    def test_expired_saved_session_cannot_restore(self):
        cookie=self.login();self.stop()
        path=Path(self.temp.name)/'sessions.json'
        data=json.loads(path.read_text());data['sessions']={key:time.time()-1 for key in data['sessions']};path.write_text(json.dumps(data))
        self.start();self.assertEqual(self.request('session',cookie=cookie)[0],401)

    def test_configure_migrates_existing_owner_without_changing_devices(self):
        from unittest.mock import patch
        from carryon.console import main
        config=Path(self.temp.name)/'gateway.json'
        devices={'mac':{'deviceToken':'d'*40,'apiToken':'a'*40}}
        config.write_text(json.dumps({'consoleToken':'x'*40,'devices':devices}))
        argv=['carryon-console','configure','--config',str(config),'--public-url','https://console.test','--username','admin']
        with patch('sys.argv',argv), patch('getpass.getpass',return_value='a long password 123'), patch('builtins.print'):
            main()
        updated=json.loads(config.read_text())
        self.assertEqual(updated['devices'],devices);self.assertNotIn('consoleToken',updated)
        self.assertNotIn('a long password 123',config.read_text())
        ConsoleAuth(updated,None).verify({'username':'admin','password':'a long password 123'})
