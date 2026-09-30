"""Credential exchanges never follow HTTP redirects."""
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_json(url, data=None, *, path='', headers=None, limit=16384, timeout=20, dev_local=False):
    """Bounded credential transport. Callers own authentication and business errors."""
    import json
    from urllib.parse import urlsplit
    from carryon.cloud.cloud_wire import endpoint, tls_context
    if not isinstance(url, str):raise ValueError('需要云端 HTTPS 地址')
    parsed = urlsplit(url)
    if parsed.scheme not in ('https', 'http') or parsed.query or parsed.fragment:
        raise ValueError('需要准确的云端 HTTPS 地址')
    endpoint(('wss' if parsed.scheme == 'https' else 'ws') + '://' + parsed.netloc + parsed.path, dev_local)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=tls_context()))
    request = urllib.request.Request(url.rstrip('/')+path, data=None if data is None else json.dumps(data).encode(),
                                     headers={'Content-Type': 'application/json', **(headers or {})})
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(limit + 1)
        if len(raw) > limit:raise ValueError('云端响应过长')
        result = json.loads(raw)
        if not isinstance(result, dict):raise ValueError('云端响应格式无效')
        return result, response.headers
