"""Real TLS upgrade: trust and hostname checks stay enabled."""
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from carryon.cloud_wire import connect, close, tls_context
from carryon.gateway import Gateway


class TLSTests(unittest.TestCase):
    def test_tls_upgrade_requires_trusted_certificate_and_matching_hostname(self):
        with tempfile.TemporaryDirectory() as temp:
            cert=Path(temp)/'cert.pem';key=Path(temp)/'key.pem'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
                '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost',
                '-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True)
            gateway=Gateway(('127.0.0.1',0),{'devices':{'mac':{'deviceToken':'d'*40,'apiToken':'a'*40}}})
            server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert,key)
            gateway.socket=server_context.wrap_socket(gateway.socket,server_side=True)
            worker=threading.Thread(target=gateway.serve_forever,daemon=True);worker.start()
            try:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    connect(f'wss://localhost:{gateway.server_port}/device')
                trusted=ssl.create_default_context(cafile=str(cert))
                with patch('carryon.cloud_wire.tls_context',return_value=trusted):
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        connect(f'wss://127.0.0.1:{gateway.server_port}/device')
                    ws=connect(f'wss://localhost:{gateway.server_port}/device')
                    try:
                        ws.send({'type':'hello','protocol':'carryon/1','deviceId':'mac','token':'d'*40})
                        self.assertEqual(ws.receive()['type'],'ready')
                    finally:close(ws)
            finally:gateway.shutdown();gateway.server_close();worker.join(3)

    @unittest.skipUnless(__import__('sys').platform=='darwin','macOS trust store')
    def test_system_roots_when_bundled_python_has_no_ca_file(self):
        empty=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch('carryon.cloud_wire.ssl.create_default_context',return_value=empty):
            result=tls_context()
        self.assertGreater(len(result.get_ca_certs()),0)
        self.assertTrue(result.check_hostname)
        self.assertEqual(result.verify_mode,ssl.CERT_REQUIRED)
