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
