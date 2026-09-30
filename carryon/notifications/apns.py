"""APNs provider transport. Credentials stay on the console host."""
import base64
import json
import re
import time
import uuid
from pathlib import Path


class APNsError(Exception):
    def __init__(self,status,reason):
        self.status=status;self.reason=reason
        super().__init__(f'APNs {status}: {reason}')


class APNsSender:
    def __init__(self,config):
        import httpx
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric import ec
        self.team=config['teamId'];self.key_id=config['keyId'];self.topic=config['topic']
        if any(not re.fullmatch(r'[A-Z0-9]{10}',v) for v in (self.team,self.key_id)):raise ValueError('APNs Team ID / Key ID 无效')
        if not re.fullmatch(r'[A-Za-z0-9.-]{1,200}',self.topic):raise ValueError('APNs topic 无效')
        path=Path(config['keyPath']).expanduser()
        if path.stat().st_mode & 0o077:raise ValueError('APNs 私钥文件权限必须为 0600 或更严格')
        self.key=load_pem_private_key(path.read_bytes(),password=None)
        if not isinstance(self.key,ec.EllipticCurvePrivateKey) or not isinstance(self.key.curve,ec.SECP256R1):raise ValueError('APNs 需要 P-256 私钥')
        self.client=httpx.Client(http2=True,timeout=10,follow_redirects=False,trust_env=False)
        self.jwt=None;self.issued=0

    def authorization(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        if self.jwt and time.time()-self.issued<3000:return self.jwt
        def b64(data):return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
        self.issued=int(time.time())
        header=b64(json.dumps({'alg':'ES256','kid':self.key_id},separators=(',',':')).encode())
        claims=b64(json.dumps({'iss':self.team,'iat':self.issued},separators=(',',':')).encode())
        content=header+'.'+claims
        r,s=decode_dss_signature(self.key.sign(content.encode(),ec.ECDSA(hashes.SHA256())))
        self.jwt=content+'.'+b64(r.to_bytes(32,'big')+s.to_bytes(32,'big'))
        return self.jwt

    def send(self,token,environment,payload,event_id):
        if environment not in ('sandbox','production') or not re.fullmatch(r'[0-9a-f]{32,512}',token):raise ValueError('APNs token 或环境无效')
        host='api.sandbox.push.apple.com' if environment=='sandbox' else 'api.push.apple.com'
        content=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        if len(content)>4096:raise ValueError('APNs payload 超过 4 KB')
        response=self.client.post(f'https://{host}/3/device/{token}',content=content,headers={
            'authorization':'bearer '+self.authorization(),'apns-topic':self.topic,'apns-push-type':'alert',
            'apns-priority':'10' if 'alert' in payload['aps'] else '5',
            'apns-expiration':str(int(time.time())+3600),
            'apns-id':str(uuid.uuid5(uuid.NAMESPACE_URL,event_id)),
            'apns-collapse-id':payload.get('threadId','badge')[:64],
            'content-type':'application/json'})
        if response.status_code!=200:
            try:reason=response.json().get('reason','Unknown')
            except ValueError:reason='InvalidResponse'
            if reason=='ExpiredProviderToken':self.jwt=None
            raise APNsError(response.status_code,reason)

    def close(self):self.client.close()
