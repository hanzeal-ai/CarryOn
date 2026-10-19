"""Unix WebSocket attachment. Never starts, owns or terminates the CLI daemon."""
import base64
import hashlib
import os
from pathlib import Path
import socket
import stat
import threading
from types import SimpleNamespace
import uuid
from contextlib import suppress

from carryon.codex_protocol.client import ProtocolClient
from carryon.errors import IPCError
from carryon.routes.websocket import WebSocket


def endpoint(home, configured=None):
    path = Path(configured).expanduser() if configured else Path(home) / 'app-server-control/app-server-control.sock'
    if not path.is_absolute(): raise ValueError('CLI socket 必须使用绝对路径')
    return path.resolve()


class CliClient(ProtocolClient):
    connection_error_label = '无法连接 Codex CLI：'
    execution_backend = 'codex-cli'
    supported_operations = ProtocolClient.supported_operations - {'side-create'}
    def __init__(self, home, *, socket_path=None):
        super().__init__(home)
        self.endpoint = endpoint(self.home, socket_path)
        self.connection = None
        self.restore_threads = set()

    def peer(self, *, runtime_directory):
        return CliClient(self.home, socket_path=self.endpoint)

    @property
    def connection_identity(self):
        return self.connection, self.session_id

    @property
    def connected(self):
        return self.connection is not None

    def connect(self):
        info = self.endpoint.stat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise IPCError('CLI socket 必须属于当前用户')
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stream = None
        try:
            sock.settimeout(10)
            sock.connect(str(self.endpoint))
            stream = sock.makefile('rb')
            key = base64.b64encode(os.urandom(16)).decode()
            sock.sendall(('GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ' + key + '\r\n\r\n').encode())
            status = stream.readline(4096)
            if not status.startswith(b'HTTP/1.1 101 '): raise IPCError('CLI socket 未接受 WebSocket 连接')
            headers, size = {}, len(status)
            while True:
                line = stream.readline(4096)
                size += len(line)
                if not line or size > 16384: raise IPCError('CLI WebSocket 握手无效')
                if line == b'\r\n': break
                name, value = line.decode('ascii').split(':', 1)
                headers[name.lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if (headers.get('sec-websocket-accept') != expected or headers.get('upgrade', '').lower() != 'websocket'
                    or 'upgrade' not in headers.get('connection', '').lower().split(', ')):
                raise IPCError('CLI WebSocket 握手校验失败')
            sock.settimeout(None)
            ws = WebSocket(SimpleNamespace(connection=sock, rfile=stream), client=True)
            ws.MAX_MESSAGE = self.MAX_FRAME
            with self.lock:
                if self.connection is not None: raise IPCError('CLI 已连接')
                self.session_id = uuid.uuid4().hex
                self.connection = ws
            threading.Thread(target=self._reader, args=(ws,), daemon=True, name='codex-cli-reader').start()
            self.initialize()
        except Exception:
            self.close()
            with suppress(OSError): sock.close()
            if stream: stream.close()
            raise

    def sidebar_snapshot(self, tid):
        # Discovery notifications are global on a shared daemon. Subscribe only
        # when the last read reports a loaded thread. The protocol has no atomic
        # subscribe-if-loaded operation; an external unload can race this resume.
        with self.lock:
            state = self.snapshots.get(tid)
            if state is not None and not state.get('_metadataOnly'):
                return 'app-server', state
        owner, state = self.refresh_snapshot(tid)
        if state['threadRuntimeStatus']['type'] in ('active', 'idle'):
            return self.snapshot(tid)
        return owner, state

    def _write(self, value):
        with self.lock: ws = self.connection
        if ws is None: raise IPCError('Codex CLI 已断开')
        ws.send(value)

    def _reader(self, ws):
        try:
            while True:
                value = ws.receive()
                with self.lock:
                    if self.connection is not ws: return
                    self.receive(value)
        except (EOFError, OSError, ValueError, KeyError, TypeError):
            pass
        finally:
            self.close(expected=ws)

    def close(self, expected=None):
        with self.lock:
            if expected is not None and self.connection is not expected: return
            ws, self.connection = self.connection, None
            self.restore_threads.update(self.following)
            self.disconnected()
        if ws:
            with suppress(OSError): ws.handler.connection.shutdown(socket.SHUT_RDWR)
            with suppress(OSError): ws.handler.connection.close()
            with suppress(OSError): ws.handler.rfile.close()
        self.on_change()
