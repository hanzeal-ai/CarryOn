"""Redeem a one-time console code without forwarding it to redirects or proxies."""
import json
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from .cloud_wire import endpoint, tls_context

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def redeem(url,code,control=False,dev_local=False):
    if not isinstance(url,str) or not isinstance(code,str) or not 20<=len(code)<=200:
        raise ValueError('需要有效的云端地址和配对码')
    if type(control) is not bool or type(dev_local) is not bool:raise ValueError('授权参数必须为布尔值')
    parsed=urlsplit(url)
    if parsed.scheme not in ('https','http'):raise ValueError('控制台地址必须为 HTTPS')
    device_url=('wss' if parsed.scheme=='https' else 'ws')+'://'+parsed.netloc+parsed.path.rstrip('/')+'/device'
    if parsed.query or parsed.fragment:raise ValueError('控制台地址不能包含查询或片段')
    endpoint(device_url,dev_local)
    request=urllib.request.Request(url.rstrip('/')+'/console/redeem',
        data=json.dumps({'code':code.strip()}).encode(),headers={'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=tls_context()))
    try:
        with opener.open(request,timeout=20) as response:
            raw=response.read(16000)
            data=json.loads(raw)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError('配对失败：配对码无效、已使用或已过期，请重新生成') from None
    from .cloud import CloudConnector
    result={'enabled':True,'url':device_url,'deviceId':data['deviceId'],'token':data['token'],
            'control':control,'devLocal':dev_local}
    CloudConnector.validate(result)
    return result


class LocalLink:
    """One in-flight authorization per local service; binding stays server-side."""
    def __init__(self, cloud, bridge, background=False):
        import threading
        self.lock=threading.Lock();self.pending=None;self.cloud=cloud;self.bridge=bridge
        self.background=background;self.closed=threading.Event();self.completed={};self.workers=[];self.failure=None

    @staticmethod
    def request(url, action, body):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.query or parsed.fragment:
            raise ValueError('控制台地址必须为 HTTPS，不能包含查询或片段')
        endpoint('wss://'+parsed.netloc+parsed.path.rstrip('/')+'/device',False)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=tls_context()))
        request=urllib.request.Request(url.rstrip('/')+'/console/link/'+action,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:
            with opener.open(request,timeout=15) as response:return json.loads(response.read(16000))
        except urllib.error.HTTPError as exc:
            status=exc.code
            try:reason=json.loads(exc.read(16000)).get('error')
            except (ValueError,AttributeError,OSError):reason=None
            finally:exc.close()
            if reason=='连接申请已拒绝':raise PermissionError(reason) from None
            if reason=='连接请求不存在或已过期':raise ValueError(reason) from None
            if status==403:raise PermissionError('云端拒绝了连接申请或申请凭证无效') from None
            raise ValueError('云端连接授权失败或已过期，请重新发起连接') from None

    def start(self, url, control):
        import time
        if not isinstance(url,str) or type(control) is not bool:raise ValueError('连接参数无效')
        with self.lock:
            if hasattr(self.cloud,'check_available'):self.cloud.check_available('wss'+url.rstrip('/')[5:]+'/device')
            import socket
            result=self.request(url,'start',{'name':socket.gethostname()[:100]})
            if not all(isinstance(result.get(k),str) and 6<=len(result[k])<=200 for k in ('id','secret','verification')):
                raise ValueError('云端连接响应无效')
            self.pending={**result,'url':url.rstrip('/'),'control':control,'expires':time.monotonic()+300}
            self.failure=None;self.completed={}
            if self.background:
                import threading
                worker=threading.Thread(target=self._wait,args=(result['id'],),daemon=True)
                self.workers=[w for w in self.workers if w.is_alive()]+[worker];worker.start()
            from urllib.parse import quote
            return {'id':result['id'],'verification':result['verification'],
                    'url':url.rstrip('/')+'/#connect='+quote(result['id'],safe='')}

    def poll(self, key):
        import time
        with self.lock:
            if key in self.completed:return self.completed[key]
            p=self.pending
            if p is None or key!=p['id'] or time.monotonic()>=p['expires']:raise ValueError('连接请求已过期或已替换')
            data=self.request(p['url'],'poll',{'id':p['id'],'secret':p['secret']})
            if data.get('pending') is True:return {'pending':True}
            config={'enabled':True,'url':'wss'+p['url'][5:]+'/device','deviceId':data.get('deviceId'),
                    'token':data.get('token'),'control':p['control']}
            self.cloud.validate(config)
            result=self.cloud.configure(config)
            self.pending=None
            from .errors import BridgeError
            from .ipc import IPCError
            try:
                self.bridge.enable();bridge_enabled=True
            except (BridgeError,IPCError,OSError,ValueError):bridge_enabled=False
            result={'pending':False,'cloud':result,'bridgeEnabled':bridge_enabled}
            if self.background:self.completed={key:result}
            return result

    def _wait(self,key):
        while not self.closed.wait(2):
            try:
                if not self.poll(key)['pending']:return
            except (ValueError,PermissionError) as exc:
                with self.lock:
                    if self.pending and self.pending['id']==key and str(exc)!='连接请求已过期或已替换':
                        self.failure=str(exc)
                return
            except (OSError,EOFError):continue

    def status(self):
        import time
        with self.lock:
            if self.pending:
                p=self.pending
                state='failed' if self.failure else 'expired' if time.monotonic()>=p['expires'] else 'pending'
                return {'state':state,'id':p['id'],'url':p['url'],'verification':p['verification'],
                        'error':self.failure,'expiresIn':max(0,int(p['expires']-time.monotonic()))}
            if self.completed:
                key,result=next(iter(self.completed.items()))
                return {'state':'bound','id':key,'bridgeEnabled':result['bridgeEnabled']}
            return {'state':'idle'}

    def close(self):
        self.closed.set()
        for worker in self.workers:worker.join(20)
