"""Authoritative API routing shared by local HTTP and the outbound cloud link."""
from urllib.parse import urlsplit, parse_qs
import re
from .errors import BridgeError


def dispatch(bridge, method, target, data=None, *, remote=False, control=False):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith('/api/'):
        raise ValueError('Invalid API path')
    path = parsed.path
    if method not in ('GET', 'POST'):
        raise ValueError('Only GET and POST are supported')
    if data is None: data = {}
    if not isinstance(data, dict): raise ValueError('请求体必须是 JSON 对象')
    if remote:
        if path in ('/api/bridge', '/api/cloud', '/api/service') or path.startswith('/api/service/'):
            raise BridgeError('云端不能管理本机授权或服务生命周期', 403)
        if method != 'GET' and not control:
            raise BridgeError('本机仅授权云端读取', 403)
    if not re.fullmatch(r'/api/(status|bridge|coordination|threads|controller|side-chats|jobs|threads/[^/]+/(history|queue|operations|messages)|side-chats/[^/]+/history|jobs/[^/]+(/acknowledge)?)', path):
        return 404, {'error':'接口不存在'}
    result = None
    def respond(status, body):
        nonlocal result
        result = (status, body)
    if method == "GET" and path == "/api/status":
        respond(200, bridge.status())
        return result
    if method == "POST" and path == "/api/bridge":
        if type(data.get("enabled")) is not bool:
            raise ValueError("enabled 必须为布尔值")
        respond(200, bridge.enable() if data["enabled"] else bridge.disable())
        return result
    bridge.require()
    if method == 'GET' and path == '/api/coordination':
        ipc, _ = bridge.require()
        with ipc.lock:
            result = {'catalogRevision': ipc.events.catalog_revision,
                      'resetRevision': ipc.events.reset_revision,
                      'threadFlags': {k: dict(v) for k, v in ipc.events.flags.items()}}
        respond(200, result)
        return result
    if method == "GET" and path == "/api/threads":
        q = parse_qs(parsed.query)
        limit = min(100, max(1, int(q.get("limit", ["100"])[0])))
        offset = max(0, int(q.get("offset", ["0"])[0]))
        respond(200, {"threads": bridge.catalog.list(limit, offset, q.get("search", [""])[0]),
                         "nextOffset": offset + limit})
    elif method == "POST" and path == "/api/controller":
        respond(200, bridge.select_controller(data.get("threadId")))
    elif method == "GET" and path == "/api/side-chats":
        respond(200, bridge.side_chats(parse_qs(parsed.query).get('parentId', [''])[0]))
    elif method == "GET" and path.startswith('/api/side-chats/') and path.endswith('/history'):
        history = bridge.side_history(parse_qs(parsed.query).get('parentId', [''])[0], path.split('/')[3])
        respond(200, {k:v for k,v in history.items() if k != 'turns'})
    elif method == "GET" and path.startswith("/api/threads/") and path.endswith("/history"):
        history = bridge.history(path.split("/")[3])
        respond(200, {k: v for k, v in history.items() if k != "turns"})
    elif method == "GET" and path.startswith('/api/threads/') and path.endswith('/queue'):
        respond(200, bridge.queue(path.split('/')[3]))
    elif method == "POST" and path == "/api/threads":
        respond(202, bridge.submit("create", data.get("requestId"), data.get("prompt")))
    elif method == "POST" and path.startswith("/api/threads/") and path.endswith("/operations"):
        from .operations import submit
        if len(path.split('/')) != 5:
            raise ValueError('无效操作路径')
        respond(202, submit(bridge, path.split('/')[3], data))
    elif method == "POST" and path.startswith("/api/threads/") and path.endswith("/messages"):
        respond(202, bridge.submit("message", data.get("requestId"), data.get("prompt"), path.split("/")[3]))
    elif method == "GET" and path == "/api/jobs":
        jobs = [bridge.refresh_job(j["id"]) for j in bridge.journal.list()[:100]]
        respond(200, {"jobs": jobs})
    elif method == "GET" and path.startswith("/api/jobs/"):
        respond(200, bridge.refresh_job(path.split("/")[3]))
    elif method == "POST" and path.startswith("/api/jobs/") and path.endswith("/acknowledge"):
        if data.get("confirmed") is not True:
            raise ValueError("请先在 Codex App 核对后传入 confirmed: true")
        respond(200, bridge.resolve(path.split("/")[3]))
    else:
        respond(404, {"error": "接口不存在"})

    return result
