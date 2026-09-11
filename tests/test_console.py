import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from connectnow.console import ConsoleServer, public_url
from connectnow.cloud import CloudConnector
from connectnow.bridge import Bridge
from connectnow.store import Journal
from connectnow.pairing import redeem
from test_cloud import Catalog, IPC, T

class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.config={'publicUrl':'http://127.0.0.1','consoleToken':'c'*40,'devices':{
            'my-mac':{'deviceToken':'d'*40,'apiToken':'a'*40},
            'other':{'deviceToken':'e'*40,'apiToken':'b'*40}}}
        self.server=ConsoleServer(('127.0.0.1',0),self.config)
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.server.origin=self.url;self.server.public_url=self.url
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.cookie='';self.journal=Journal(self.root/'journal.sqlite')
        self.bridge=Bridge('fake',Catalog(),self.journal,IPC);self.connector=CloudConnector(self.bridge,self.root)
    def tearDown(self):
        self.connector.stop();self.bridge.disable()
        if self.bridge.realtime:
            for worker in self.bridge.realtime.workers:worker.join(3)
        self.server.shutdown();self.server.server_close();self.worker.join(3)
        self.journal.conn.close();self.temp.cleanup()
    def call(self,method,path,body=None,origin=True):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Content-Type':'application/json','Cookie':self.cookie}
        if origin:headers['Origin']=self.url if origin is True else origin
        c.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers)
        r=c.getresponse();raw=r.read();cookie=r.getheader('Set-Cookie')
        if cookie:self.cookie=cookie.split(';')[0]
        result=(r.status,json.loads(raw) if r.getheader('Content-Type','').startswith('application/json') else raw,cookie)
        c.close();return result
    def login(self):
        status,body,cookie=self.call('POST','/console/login',{'token':'c'*40})
        self.assertEqual(status,200);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
    def test_console_auth_origin_logout_and_secret_boundary(self):
        self.assertEqual(self.call('GET','/console/session')[0],401)
        self.assertEqual(self.call('POST','/console/login',{'token':'c'*40},False)[0],403)
        self.assertEqual(self.call('POST','/console/login',{'token':'a'*40})[0],403)
        self.login();result=self.call('GET','/console/session')
        self.assertEqual(result[0],200)
        self.assertNotIn('Token',json.dumps(result[1]));self.assertNotIn('a'*40,json.dumps(result[1]))
        self.assertEqual(self.call('POST','/console/pairing',{'deviceId':'my-mac'},'https://evil.test')[0],403)
        self.assertEqual(self.call('GET','/console/devices/not-owned')[0],403)
        old=self.cookie;self.assertEqual(self.call('POST','/console/logout',{})[0],200)
        self.cookie=old;self.assertEqual(self.call('GET','/console/session')[0],401)
    def test_link_history_auth_and_clear_preserves_devices_and_pending(self):
        self.assertEqual(self.call('DELETE','/console/link/history')[0],401)
        self.login()
        done=self.server.links.start('Done');pending=self.server.links.start('Pending')
        self.server.links.reject(done['id'])
        body=self.call('GET','/console/link/pending')[1]
        self.assertEqual(body['history'][0]['result'],'rejected')
        self.assertNotIn('secret',json.dumps(body))
        self.assertEqual(self.call('DELETE','/console/link/history',origin='https://evil.test')[0],403)
        devices=dict(self.server.config['devices'])
        self.assertEqual(self.call('DELETE','/console/link/history')[0],200)
        body=self.call('GET','/console/link/pending')[1]
        self.assertEqual(body['history'],[])
        self.assertEqual(body['requests'][0]['id'],pending['id'])
        self.assertEqual(self.server.config['devices'],devices)

    def test_pairing_once_and_end_to_end_read_only(self):
        self.login();code=self.call('POST','/console/pairing',{'deviceId':'my-mac'})[1]['code']
        config=redeem(self.url,code,dev_local=True)
        self.assertFalse(config['control']);self.connector.configure(config);self.bridge.enable()
        end=time.monotonic()+4
        while not self.connector.status()['connected'] and time.monotonic()<end:time.sleep(.02)
        self.assertTrue(self.connector.status()['connected'])
        with self.assertRaises(Exception):redeem(self.url,code,dev_local=True)
        route='/console/devices/my-mac/request'
        self.assertEqual(self.call('POST',route,{'method':'GET','path':'/api/threads'})[1]['threads'][0]['id'],T)
        self.assertEqual(self.call('POST',route,{'method':'POST','path':'/api/bridge','body':{'enabled':True}})[0],403)
        self.assertEqual(self.call('POST',route,{'method':'POST','path':f'/api/threads/{T}/messages','body':{'requestId':'test-console','prompt':'test'}})[0],403)
        status,stream,_=self.call('POST','/console/devices/my-mac/streams',{'threadId':T,'threadIds':[T]})
        self.assertEqual(status,200)
        original_cookie=self.cookie;self.login()
        self.assertEqual(self.call('GET','/console/devices/my-mac/streams/'+stream['streamId'])[0],403)
        self.cookie=original_cookie
        sid=stream['streamId'];self.assertEqual(self.call('GET',f'/console/devices/my-mac/streams/{sid}?after=-1')[0],200)
        self.assertEqual(self.call('DELETE',f'/console/devices/my-mac/streams/{sid}')[0],200)
        _,stale,_=self.call('POST','/console/devices/my-mac/streams',{'threadId':T})
        with self.server.auth_lock:self.server.console_streams[stale['streamId']]['last']=time.monotonic()-61
        self.server.service_actions()
        self.assertEqual(self.call('GET','/console/devices/my-mac/streams/'+stale['streamId'])[0],404)
        self.connector.stop()
        end=time.monotonic()+3
        while 'my-mac' in self.server.devices and time.monotonic()<end:time.sleep(.02)
        self.assertEqual(self.call('POST',route,{'method':'GET','path':'/api/threads'})[0],503)
    def test_pairing_expiry_and_static_example(self):
        self.login();code=self.call('POST','/console/pairing',{'deviceId':'my-mac'})[1]['code']
        with self.server.auth_lock:
            self.server.codes={k:(v[0],0) for k,v in self.server.codes.items()}
        self.assertEqual(self.call('POST','/console/redeem',{'code':code},False)[0],403)
        page=self.call('GET','/example.html')[1]
        self.assertIn(b'console-mode.js',page)
        self.assertIn(b'CONNECTNOW_CLOUD=true',self.call('GET','/console-mode.js')[1]);self.assertIn(b'cloud-console-client.js',page)
        self.assertNotIn(b'c'*40,page)
        self.assertEqual(self.call('GET','/gateway.json')[0],404)
    def test_proxy_prefix_assets_and_secure_cookie(self):
        self.server.public_url='https://console.test/connectnow'
        self.server.origin='https://console.test';self.server.prefix='/connectnow'
        result=self.call('POST','/console/login',{'token':'c'*40},'https://console.test')
        self.assertEqual(result[0],200)
        self.assertIn('; Secure',result[2]);self.assertIn('Path=/connectnow/console/',result[2])
        page=self.call('GET','/example.html',origin=False)[1]
        self.assertIn(b'src="/connectnow/app.js"',page)
        self.assertIn(b'src="/connectnow/mobile-ui.js"',page)
        self.assertIn(b'href="/connectnow/mobile.css"',page)
        for asset in ('mobile-ui.js', 'mobile.css'):
            status, content, _ = self.call('GET', '/' + asset, origin=False)
            self.assertEqual(status, 200)
            self.assertTrue(content)
        self.assertIn(b'src="/connectnow/console-mode.js"',page)
    def test_early_offline_response_does_not_poison_next_http_request(self):
        self.login()
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Content-Type':'application/json','Cookie':self.cookie,'Origin':self.url}
        c.request('POST','/console/devices/my-mac/request',body=json.dumps({'method':'GET','path':'/api/status'}),headers=headers)
        r=c.getresponse();self.assertEqual(r.status,503);r.read()
        self.assertTrue(r.will_close)
        c.request('GET','/console/session',headers=headers)
        r=c.getresponse();self.assertEqual(r.status,200);self.assertIn('devices',json.loads(r.read()));c.close()
    def test_public_url_validation(self):
        for url in ['http://remote.test','https://remote.test/x"y','https://remote.test/a\n','https://u:p@remote.test']:
            with self.assertRaises(ValueError):public_url(url)
