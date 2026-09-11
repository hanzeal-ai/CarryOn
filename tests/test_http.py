import http.client
from html.parser import HTMLParser
import json
import threading
import unittest
from connectnow.server import Server, Handler


class FakeBridge:
    def status(self): return {"enabled":False}
    def require(self):
        from connectnow.bridge import BridgeError
        raise BridgeError("disabled", 403)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server=Server(("127.0.0.1",0),Handler)
        self.server.token="a"*43
        self.server.bridge=FakeBridge()
        self.port=self.server.server_port
        self.server.allowed_hosts={f"127.0.0.1:{self.port}"}
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.port)
        conn.request("GET",path,headers=headers or {})
        response=conn.getresponse();result=(response.status,response.read(),dict(response.getheaders()));conn.close();return result
    def test_token_required(self):
        self.assertEqual(self.request('/api/status')[0],401)
    def test_origin_and_host_rejected(self):
        auth={"Authorization":"Bearer "+self.server.token}
        self.assertEqual(self.request('/api/status',{**auth,"Origin":"https://attacker.test"})[0],403)
        self.assertEqual(self.request('/api/status',{**auth,"Host":"attacker.test"})[0],403)
    def test_auth_does_not_override_disabled_gate(self):
        auth={"Authorization":"Bearer "+self.server.token}
        self.assertEqual(self.request('/api/status',auth)[0],200)
        self.assertEqual(self.request('/api/threads',auth)[0],403)
    def test_static_page_cannot_expose_runtime_token(self):
        status,body,headers=self.request('/example.html')
        self.assertEqual(status,200)
        self.assertIn('frame-ancestors',headers['Content-Security-Policy'])
        self.assertNotIn(self.server.token.encode(),body)
        self.assertEqual(self.request('/.runtime/token')[0],401)

    def test_every_page_asset_is_served_without_authentication(self):
        scripts = []
        styles = []
        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == 'script': scripts.append(dict(attrs)['src'])
                if tag == 'link' and dict(attrs).get('rel') == 'stylesheet': styles.append(dict(attrs)['href'])
        Parser().feed(self.request('/example.html')[1].decode())
        self.assertIn('/client.js', scripts)
        self.assertIn('/mobile.css', styles)
        self.assertIn('/mobile-ui.js', scripts)
        for path in scripts + styles:
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn('javascript' if path in scripts else 'text/css', headers['Content-Type'])
                self.assertTrue(body)
    def test_operation_post_obeys_auth_origin_and_bridge_gate(self):
        path='/api/threads/11111111-1111-4111-8111-111111111111/operations'
        body=json.dumps({'requestId':'operation-123','action':'compact'})
        auth={'Authorization':'Bearer '+self.server.token,'Content-Type':'application/json'}
        for headers,expected in (({'Content-Type':'application/json'},401),
                                 ({**auth,'Origin':'https://attacker.test'},403),(auth,403)):
            conn=http.client.HTTPConnection('127.0.0.1',self.port)
            conn.request('POST',path,body,headers)
            response=conn.getresponse();response.read();conn.close()
            self.assertEqual(response.status,expected)


if __name__=='__main__':unittest.main()
