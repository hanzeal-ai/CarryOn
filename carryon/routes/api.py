"""Authoritative API routing shared by local HTTP and the outbound cloud link."""
from urllib.parse import urlsplit, parse_qs
import re
from carryon.errors import BridgeError


def dispatch(bridge, method, target, data=None, *, remote=False, control=False, source=None, authorize=None):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith('/api/'):
        raise ValueError('Invalid API path')
    path = parsed.path
    if method not in ('GET', 'POST'):
        raise ValueError('Only GET and POST are supported')
    if data is None: data = {}
    if not isinstance(data, dict): raise ValueError('请求体必须是 JSON 对象')
    if path=='/api/standby' and method=='GET':
        bridge.require()
        if not hasattr(bridge,'standby'):return 200,{'supported':False,'enabled':False,'effective':False}
        return 200,bridge.standby.status()
    if not remote and (path in ('/api/projects','/api/workspace/threads','/api/activity','/api/notifications','/api/notifications/read','/api/notifications/clear-read','/api/notifications/preferences','/api/notifications/push') or re.fullmatch(r'/api/projects/[0-9a-f]{64}/threads',path)):
        if not hasattr(bridge,'workspace'):raise BridgeError('工作区功能尚未启用，请升级本机服务',503)
        return bridge.workspace.dispatch('local',method,path,data,parse_qs(parsed.query))
    if remote:
        if path in ('/api/bridge', '/api/cloud', '/api/service') or path.startswith('/api/service/'):
            raise BridgeError('云端不能管理本机授权或服务生命周期', 403)
        if not control and path.endswith('/voice'):
            raise BridgeError('本机未授权云端访问语音', 403)
        if method != 'GET' and not control:
            raise BridgeError('本机仅授权云端读取', 403)
    if not re.fullmatch(r'/api/(status|models|search|creation/references|usage|usage/reset|bridge|coordination|threads|sections|sections/[^/]+|sections/[^/]+/threads|archived|side-chats|jobs|threads/[^/]+/(subagents|history|search|search-anchor|queue|terminals|plugins|files/search|skills/config|skills|mentions|goal|voice|voice/audio|operations|messages|compose|session|fork|archive|unarchive|rename|section|side-chats|(?:images|artifacts)/[0-9a-f]{64})|side-chats/[^/]+/(history|compose|operations|close|(?:images|artifacts)/[0-9a-f]{64})|jobs/[^/]+(/acknowledge)?)', path):
        return 404, {'error':'接口不存在'}
    result = None
    def respond(status, body):
        nonlocal result
        result = (status, body)
    if method == "GET" and path == "/api/status":
        respond(200, bridge.lifecycle.status() if hasattr(bridge, 'lifecycle') else bridge.status())
        return result
    if method == "POST" and path == "/api/bridge":
        if type(data.get("enabled")) is not bool:
            raise ValueError("enabled 必须为布尔值")
        respond(200, bridge.lifecycle.configure(data['enabled']) if hasattr(bridge, 'lifecycle')
                else bridge.enable() if data["enabled"] else bridge.disable())
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
    if method == "GET" and path == "/api/usage":
        from carryon.usage import read
        respond(200, read(bridge.catalog.home))
    elif method == 'POST' and path == '/api/usage/reset':
        from carryon.quota_reset import submit
        respond(200, submit(bridge, data, source, authorize))
    elif method == 'GET' and path == '/api/creation/references':
        from carryon.sessions.creation_references import discover
        respond(200, discover(bridge, parse_qs(parsed.query).get('projectId', [None])[0], authorize))
    elif method == "GET" and path == "/api/models":
        from carryon.models import catalog
        respond(200, catalog(bridge.catalog.home))
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/search-anchor'):
        from carryon.sessions.search import anchor
        respond(200, anchor(bridge, path.split('/')[3], parse_qs(parsed.query), authorize))
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/files/search'):
        from carryon.sessions.file_references import read
        respond(200, read(bridge, path.split('/')[3], parse_qs(parsed.query).get('query', [''])[0], authorize))
    elif method == 'GET' and (path == '/api/search' or path.startswith('/api/threads/') and path.endswith('/search')):
        from carryon.sessions.search import page
        respond(200, page(bridge, parse_qs(parsed.query), None if path == '/api/search' else path.split('/')[3], authorize))
    elif method == 'POST' and (path == '/api/sections' or re.fullmatch(r'/api/sections/[^/]+', path)):
        from carryon.sessions.section_management import submit
        respond(202, submit(bridge, None if path == '/api/sections' else path.split('/')[3], data, source, authorize))
    elif path.startswith('/api/threads/') and path.endswith('/plugins'):
        from carryon.sessions.plugins import read, submit
        tid = path.split('/')[3]
        if method == 'GET':
            query = parse_qs(parsed.query)
            discovery = None
            if 'search' in query:
                discovery = {'searchTerm': query['search'][0].strip(), 'scope': query.get('scope', ['global'])[0], 'cursor': query.get('cursor', [None])[0]}
            respond(200, read(bridge, tid, query.get('pluginId', [None])[0], authorize, discovery))
        elif method == 'POST': respond(202, submit(bridge, tid, data, source, authorize))
        else: raise BridgeError('方法不支持', 405)
    elif path.startswith('/api/threads/') and path.endswith('/terminals'):
        from carryon.sessions.terminals import read, submit
        respond(200, read(bridge, path.split('/')[3], parse_qs(parsed.query), authorize)) if method == 'GET' else respond(202, submit(bridge, path.split('/')[3], data, source, authorize))
    elif method == 'GET' and (path == '/api/sections' or path.startswith('/api/sections/') and path.endswith('/threads')):
        from carryon.sessions.sections import page
        respond(200, page(bridge, parse_qs(parsed.query), None if path == '/api/sections' else path.split('/')[3], authorize))
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/section'):
        from carryon.sessions.sections import membership
        respond(200, membership(bridge, path.split('/')[3], authorize))
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith('/section'):
        from carryon.sessions.sections import submit
        respond(202, submit(bridge, path.split('/')[3], data, source, authorize))
    elif method == "GET" and path == "/api/archived":
        from carryon.sessions.native_metadata import supported
        query = parse_qs(parsed.query)
        limit = min(100, max(1, int(query.get('limit', ['100'])[0])))
        offset = max(0, int(query.get('offset', ['0'])[0]))
        rows = bridge.catalog.archived_list(limit, offset, query.get('search', [''])[0])
        respond(200, {'threads': rows, 'nextOffset': offset + len(rows), 'supportsRestore': supported(bridge)})
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith(('/archive', '/unarchive')):
        from carryon.sessions.archives import submit
        respond(202, submit(bridge, path.split('/')[3], path.split('/')[4], data, source, authorize))
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith('/rename'):
        from carryon.sessions.renaming import submit
        respond(202, submit(bridge, path.split('/')[3], data, source, authorize))
    elif method == "GET" and path == "/api/threads":
        q = parse_qs(parsed.query)
        limit = min(100, max(1, int(q.get("limit", ["100"])[0])))
        offset = max(0, int(q.get("offset", ["0"])[0]))
        respond(200, {"threads": bridge.catalog.list(limit, offset, q.get("search", [""])[0]),
                         "nextOffset": offset + limit})
    elif method == "GET" and path == "/api/side-chats":
        respond(200, bridge.side_chats(parse_qs(parsed.query).get('parentId', [''])[0]))
    elif method == "GET" and path.startswith('/api/side-chats/') and path.endswith('/history'):
        history = bridge.side_history(parse_qs(parsed.query).get('parentId', [''])[0], path.split('/')[3])
        respond(200, history)
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith('/side-chats'):
        from carryon.sessions.side_creation import submit
        respond(202, submit(bridge, path.split('/')[3], data, source, authorize))
    elif method == 'POST' and path.startswith('/api/side-chats/') and path.endswith('/close'):
        from carryon.sessions.side_creation import close
        respond(200, close(bridge, path.split('/')[3], data, source, authorize))
    elif method == 'POST' and path.startswith('/api/side-chats/') and path.endswith(('/compose', '/operations')):
        parent = data.get('parentId')
        from carryon.sessions.catalog import valid_id
        valid_id(parent)
        tid = path.split('/')[3]
        bridge = bridge.side_endpoint(parent, tid)
        if path.endswith('/compose'):
            respond(202, bridge.compose(tid, data.get('requestId'), data.get('prompt'), data.get('images'), source, authorize, parent_id=parent, skills=data.get('skills'),mentions=data.get('mentions'),files=data.get('files')))
        else:
            from carryon.sessions.operations import submit
            respond(202, submit(bridge, tid, data, source, authorize, parent_id=parent))
    elif method == 'GET' and ('/images/' in path or '/artifacts/' in path):
        parts = path.split('/')
        parent = parse_qs(parsed.query).get('parentId', [''])[0] if parts[2] == 'side-chats' else None
        respond(200, (bridge.image if parts[4] == "images" else bridge.artifact)(parts[3], parts[5], parent))
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith('/session'):
        handler = getattr(bridge, 'session_control', None)
        if handler is None: raise BridgeError('当前工作区未启用会话加载', 409)
        respond(200, handler(path.split('/')[3], data, source, authorize))
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/voice'):
        from carryon.app_server.realtime_voice import read
        after = parse_qs(parsed.query).get('after', ['0'])
        if len(after) != 1 or not after[0].isdigit() or len(after[0]) > 16: raise ValueError('语音游标无效')
        respond(200, read(bridge, path.split('/')[3], int(after[0])))
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith('/voice/audio'):
        from carryon.app_server.realtime_voice import append_audio
        respond(200, append_audio(bridge, path.split('/')[3], data, authorize))
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/mentions'):
        from carryon.sessions.mentions import discover
        respond(200, discover(bridge, path.split('/')[3]))
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith('/skills/config'):
        from carryon.sessions.skill_configuration import submit
        respond(202, submit(bridge, path.split('/')[3], data, source, authorize))
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/skills'):
        from carryon.sessions.skills import discover
        respond(200, discover(bridge, path.split('/')[3]))
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/goal'):
        from carryon.app_server.goals import discover
        respond(200, discover(bridge, path.split('/')[3]))
    elif method == "GET" and path.startswith("/api/threads/") and path.endswith("/history"):
        values = parse_qs(parsed.query, keep_blank_values=True).get('limit', ['40'])
        if len(values) != 1 or not re.fullmatch(r'[0-9]{1,4}', values[0]) or not 1 <= int(values[0]) <= 4000:
            raise ValueError('limit 必须为 1 到 4000 的整数')
        history = bridge.history(path.split("/")[3], limit=int(values[0]))
        respond(200, history)
    elif method == 'GET' and path.startswith('/api/threads/') and path.endswith('/subagents'):
        respond(200, bridge.subagents.list(path.split('/')[3]))
    elif method == "GET" and path.startswith('/api/threads/') and path.endswith('/queue'):
        respond(200, bridge.queue(path.split('/')[3]))
    elif method == "POST" and path == "/api/threads":
        if getattr(bridge.catalog, 'independent', False):
            from carryon.app_server.app_creation import submit
            respond(202, submit(bridge, data.get('requestId'), data.get('prompt'), data.get('projectId'), source, authorize, images=data.get('images'), settings=data.get('settings'), skills=data.get('skills'), mentions=data.get('mentions')))
        else:
            from carryon.sessions.creation import submit
            respond(202, submit(bridge, data.get('requestId'), data.get('prompt'), data.get('projectId'), source, authorize, images=data.get('images'), settings=data.get('settings'), skills=data.get('skills'), mentions=data.get('mentions')))
    elif method == "POST" and path.startswith("/api/threads/") and path.endswith("/operations"):
        from carryon.sessions.operations import submit
        if len(path.split('/')) != 5:
            raise ValueError('无效操作路径')
        respond(202, submit(bridge, path.split('/')[3], data, **({'source':source,'authorize':authorize} if source else {})))
    elif method == 'POST' and path.startswith('/api/threads/') and path.endswith('/fork'):
        from carryon.sessions.forking import submit
        respond(202, submit(bridge, path.split('/')[3], data, source, authorize))
    elif method == "POST" and path.startswith('/api/threads/') and path.endswith('/compose'):
        respond(202,bridge.compose(path.split('/')[3],data.get('requestId'),data.get('prompt'),data.get('images'),source,authorize,skills=data.get('skills'),mentions=data.get('mentions'),files=data.get('files')))
    elif method == "POST" and path.startswith("/api/threads/") and path.endswith("/messages"):
        respond(202, bridge.submit("message", data.get("requestId"), data.get("prompt"), path.split("/")[3], images=data.get("images"), skills=data.get('skills'),mentions=data.get('mentions'),files=data.get('files'), **({"source":source,"authorize":authorize} if source else {})))
    elif method == "GET" and path == "/api/jobs":
        jobs = [bridge.refresh_job(j["id"]) for j in bridge.journal.list(limit=100)]
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
