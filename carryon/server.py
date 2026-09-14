"""Loopback-only HTTP API and example UI. Run: python3 -m carryon.server"""
import argparse
import hmac
import json
import os
import secrets
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .bridge import Bridge
from .errors import BridgeError
from .catalog import Catalog
from .ipc import IPCError
from .store import Journal
from .websocket import upgrade, serve

from .paths import assets, state_dir, save_json
from . import __version__

ROOT = assets()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    stream_slots = threading.BoundedSemaphore(16)


class Handler(BaseHTTPRequestHandler):
    server_version = "CarryOn/0.1"

    def log_message(self, *_):
        pass  # Never log token, prompt or conversation content.

    def reply(self, status, body, content_type="application/json; charset=utf-8"):
        data = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def gate(self):
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts:
            raise BridgeError("Host 不被允许", 403)
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            raise BridgeError("禁止跨站请求；外部程序请使用服务端 API", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise BridgeError("禁止跨站请求", 403)

    def auth(self):
        expected = "Bearer " + self.server.token
        if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            raise BridgeError("请双击 CarryOn 应用或运行 carryon open 完成本机配对", 401)

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("不支持 Transfer-Encoding")
        length = int(self.headers.get("Content-Length", "0"))
        from .images import MAX_REQUEST_BYTES
        limit=MAX_REQUEST_BYTES if urlsplit(self.path).path.endswith(("/messages", "/compose", "/operations")) else 100000
        if not 0 < length <= limit:
            raise ValueError("请求体为空或过大")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type 必须为 application/json")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def handle_api(self, method):
        try:
            self.connection.settimeout(25)
            self.gate()
            parsed = urlsplit(self.path)
            path = parsed.path
            if method == "GET" and path in ("/", "/example.html", "/logo.svg", "/favicon.png", "/apple-touch-icon.png", "/app.js", "/subagents.js", "/notification-client.js", "/client.js", "/cloud-console-client.js", "/console-login.js", "/qrcode.js", "/timeline.js", "/operations.js", "/style.css", "/mobile.css", "/mobile-ui.js"):
                filename = "example.html" if path == "/" else path[1:]
                mime = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml", "png": "image/png"}[filename.rsplit(".", 1)[1]]
                self.reply(200, (ROOT / filename).read_bytes(), mime + "; charset=utf-8")
                return
            if method == "GET" and path == "/api/stream":
                if not self.server.stream_slots.acquire(blocking=False):
                    self.reply(503, {"error": "实时连接数已达上限"})
                    return
                try:
                    upgrade(self)
                    serve(self)
                finally:
                    self.server.stream_slots.release()
                return
            self.auth()
            if method=='POST' and (path.startswith('/api/cloud') or path.startswith('/api/service') or path in ('/api/bridge','/api/controller','/api/notifications/preferences')):
                if self.headers.get('Origin') is not None or any(key.lower().startswith('sec-fetch-') for key in self.headers):
                    raise BridgeError('本机配置仅支持 CLI 或桌面端',403)
            bridge = self.server.bridge
            data = self.body() if method == "POST" else {}
            if path == '/api/service' and method == 'GET':
                self.reply(200, self.server.service_info)
                return
            if path == '/api/service/standby' and method in ('GET', 'POST'):
                result = self.server.standby.configure(data.get('enabled')) if method == 'POST' else self.server.standby.status()
                self.reply(200, result)
                return
            if path == '/api/service/stop' and method == 'POST':
                self.reply(200, {'stopping': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == '/api/cloud' and method == 'GET':
                self.reply(200, self.server.cloud.status())
                return
            if path == '/api/cloud/control' and method == 'POST':
                self.reply(200,self.server.cloud.set_control(data.get('control'),data.get('id')));return
            if path == '/api/cloud/link/status' and method == 'GET':
                self.reply(200,self.server.local_link.status());return
            if path == '/api/cloud/link/start' and method == 'POST':
                self.reply(200,self.server.local_link.start(data.get('url'),data.get('control',False)));return
            if path == '/api/cloud/link/poll' and method == 'POST':
                self.reply(200,self.server.local_link.poll(data.get('id')));return
            if path == '/api/cloud/pair' and method == 'POST':
                from .pairing import redeem
                config = redeem(data.get('url'),data.get('code'),data.get('control',False))
                result=self.server.cloud.configure(config)
                bridge.enable()
                self.reply(200,result)
                return
            if path == '/api/cloud' and method == 'POST':
                self.reply(200, self.server.cloud.configure(data))
                return
            from .api import dispatch
            status, result = dispatch(bridge, method, self.path, data)
            self.reply(status, result)
        except BridgeError as exc:
            self.reply(exc.status, {"error": str(exc)})
        except IPCError as exc:
            self.reply(409, {"error": str(exc), "uncertain": exc.uncertain})
        except (ValueError, TypeError, KeyError) as exc:
            self.reply(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.reply(500, {"error": "本地服务处理失败，请检查 Codex 数据格式与服务状态"})

    def do_GET(self):
        self.handle_api("GET")

    def do_POST(self):
        self.handle_api("POST")

    def do_OPTIONS(self):
        self.reply(403, {"error": "不提供跨域浏览器访问，请通过配对页面或服务端 API 使用"})


def run(port, codex_home, directory):
    from .cloud_manager import CloudManager
    import fcntl
    import uuid
    from .paths import private_dir
    os.umask(0o077)
    private_dir(directory)
    lock = (directory / 'server.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError('这个状态目录已有 CarryOn 实例运行')
    token_file = directory / 'token'
    if token_file.exists():
        token = token_file.read_text().strip()
        if len(token) < 32: raise ValueError('token 文件无效')
    else:
        token = secrets.token_urlsafe(32)
        token_file.write_text(token)
    token_file.chmod(0o600)
    journal = Journal(directory / 'jobs.sqlite')
    bridge = Bridge(codex_home / 'ipc/ipc.sock', Catalog(codex_home), journal)
    from .lifecycle import BridgeLifecycle
    bridge.lifecycle = BridgeLifecycle(bridge)
    server = Server(('127.0.0.1', port), Handler)
    bridge.listener_info = {"listenHost": server.server_address[0], "port": server.server_port}
    server.bridge, server.token = bridge, token
    server.allowed_hosts = {f'127.0.0.1:{server.server_port}', f'localhost:{server.server_port}'}
    server.service_info = {'instanceId':str(uuid.uuid4()), 'pid':os.getpid(), 'port':server.server_port,
                           'version':__version__, 'codexHome':str(codex_home)}
    from .standby import RemoteStandby
    server.standby = RemoteStandby(directory)
    bridge.standby=server.standby
    from .workspace import Workspace
    bridge.workspace=Workspace(bridge)
    server.cloud = CloudManager(bridge, directory)
    from .pairing import LocalLink
    server.local_link = LocalLink(server.cloud, bridge, background=True)
    save_json(directory/'service.json', server.service_info)
    print(f"CarryOn ready: http://127.0.0.1:{server.server_port}/", flush=True)

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        from .services import register
        register(directory,port=server.server_port,codex_home=codex_home)
        bridge.lifecycle.start()
        bridge.workspace.start()
        server.standby.start()
        server.cloud.start()
        server.serve_forever()
    finally:
        bridge.lifecycle.close()
        bridge.workspace.close()
        server.standby.close()
        server.local_link.close()
        server.cloud.stop()
        bridge.disable()
        if bridge.realtime:
            for session in list(bridge.realtime.sessions): session.close()
            for worker in bridge.realtime.workers: worker.join(2)
        server.server_close()
        # The process owns the journal. Let process exit close it after daemon
        # dispatchers; closing here can race their final uncertain-state update.
        record = directory/'service.json'
        if record.exists() and json.loads(record.read_text()).get('instanceId') == server.service_info['instanceId']:
            record.unlink()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description='CarryOn 本地 Codex 桥接')
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--codex-home', type=Path, default=Path.home()/'.codex')
    parser.add_argument('--state-dir', type=Path, default=state_dir())
    args = parser.parse_args()
    run(args.port,args.codex_home.expanduser().resolve(),args.state_dir.expanduser().resolve())


if __name__ == '__main__': main()
