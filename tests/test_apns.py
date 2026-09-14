import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
try:
    import httpx
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    AVAILABLE=True
except ImportError:AVAILABLE=False
from carryon.apns import APNsSender, APNsError

@unittest.skipUnless(AVAILABLE,'install the apns extra to test provider HTTP/2 and signing')
class APNsTests(unittest.TestCase):
    def test_es256_payload_environment_and_provider_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            key=ec.generate_private_key(ec.SECP256R1());path=Path(tmp)/'test.p8'
            path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));os.chmod(path,0o600)
            sender=APNsSender({'teamId':'A'*10,'keyId':'B'*10,'topic':'com.example.app','keyPath':str(path)})
            self.addCleanup(sender.close)
            calls=[]
            def response(request):
                calls.append(request)
                return httpx.Response(200)
            sender.client.close();sender.client=httpx.Client(transport=httpx.MockTransport(response))
            sender.send('ab'*32,'sandbox',{'aps':{'badge':2}},'event1')
            request=calls[0]
            self.assertEqual(request.url.host,'api.sandbox.push.apple.com')
            self.assertEqual(request.headers['apns-topic'],'com.example.app')
            self.assertEqual(request.headers['apns-push-type'],'alert')
            header,claims,signature=request.headers['authorization'].split(' ')[1].split('.')
            raw=base64.urlsafe_b64decode(signature+'==')
            der=encode_dss_signature(int.from_bytes(raw[:32],'big'),int.from_bytes(raw[32:],'big'))
            key.public_key().verify(der,(header+'.'+claims).encode(),ec.ECDSA(hashes.SHA256()))
            self.assertEqual(json.loads(request.content),{'aps':{'badge':2}})
            sender.client.close();sender.client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(410,json={'reason':'Unregistered'})))
            with self.assertRaises(APNsError) as failure:sender.send('ab'*32,'production',{'aps':{'badge':0}},'event2')
            self.assertEqual(failure.exception.status,410)
