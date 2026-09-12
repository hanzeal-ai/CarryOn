import http.server
import json
import threading
import unittest
from unittest.mock import patch

from carryon.account_client import request


class AccountTransportTests(unittest.TestCase):
    def test_redirect_does_not_forward_credentials_and_remote_errors_are_sanitized(self):
        hits=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                hits.append(self.path)
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                self.send_response(302 if self.path.startswith('/redirect/') else 503)
                self.send_header('Location','/capture')
                self.end_headers();self.wfile.write(b'{"error":"secret-password-from-server"}')
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            for prefix in ('/redirect','/fail'):
                with self.assertRaises(ValueError) as raised:
                    request(f'http://127.0.0.1:{server.server_port}'+prefix,'change',{'password':'secret-password-from-server'},dev_local=True)
                self.assertNotIn('secret-password',str(raised.exception))
            self.assertEqual(hits,['/redirect/console/account/change','/fail/console/account/change'])
        finally:server.shutdown();server.server_close();worker.join(3)

    def test_transport_failure_is_not_retried(self):
        with patch('carryon.account_client.urllib.request.build_opener') as build:
            build.return_value.open.side_effect=TimeoutError('secret-password')
            with self.assertRaisesRegex(ValueError,'不会自动重试'):
                request('https://example.test','change',{'password':'secret-password'})
            self.assertEqual(build.return_value.open.call_count,1)

    def test_old_console_is_reported_as_needing_upgrade(self):
        import urllib.error
        with patch('carryon.account_client.urllib.request.build_opener') as build:
            build.return_value.open.side_effect=urllib.error.HTTPError('https://example.test',401,'',{},None)
            with self.assertRaisesRegex(ValueError,'升级云端'):
                request('https://example.test','status')
