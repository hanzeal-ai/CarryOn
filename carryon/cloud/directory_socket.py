"""Account-scoped directory invalidations, independent of any selected device."""
import hashlib
import json
import socket
import struct
import threading
import time

from carryon.routes.websocket import WebSocket

HEARTBEAT_INTERVAL = 15
READ_TIMEOUT = 45


def snapshot(server, key):
    with server.auth_lock:
        if server.sessions.get(key, 0) <= time.monotonic():
            raise PermissionError('登录已过期，请重新登录')
        session = server.session_info(key)
        pending = server.binding_invites.pending(server.auth.identity(key))
    # Only an authorized account's public projection affects its invalidation.
    body = json.dumps([session, pending], sort_keys=True, ensure_ascii=False)
    expiry = min((item['expiresAt'] for item in pending['requests']), default=None)
    return hashlib.sha256(body.encode()).hexdigest(), expiry


def serve(handler, key):
    server = handler.server
    ws = WebSocket(handler)
    closed = threading.Event()

    def finish():
        closed.set()
        with server.directory_changed:
            server.directory_changed.notify_all()
        try: handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError: pass

    def pump():
        revision = -1
        signature = None
        expiry = None
        heartbeat = time.monotonic() + HEARTBEAT_INTERVAL
        try:
            while not closed.is_set() and not server.directory_closed:
                with server.directory_changed:
                    changed = revision != server.directory_revision
                    revision = server.directory_revision
                with server.auth_lock:
                    if server.sessions.get(key, 0) <= time.monotonic():
                        raise PermissionError('登录已过期，请重新登录')
                if changed or expiry is not None and time.time() >= expiry:
                    current, expiry = snapshot(server, key)
                    if current != signature:
                        ws.send({'type': 'directory-changed', 'revision': current})
                        signature = current
                if time.monotonic() >= heartbeat:
                    ws.send({'type': 'ping'})
                    heartbeat = time.monotonic() + HEARTBEAT_INTERVAL
                timeout = max(0, heartbeat - time.monotonic())
                if expiry is not None: timeout = min(timeout, max(0, expiry - time.time()))
                with server.directory_changed:
                    if revision == server.directory_revision and not closed.is_set() and not server.directory_closed:
                        server.directory_changed.wait(timeout)
        except PermissionError as error:
            try:
                ws.send({'type': 'error', 'status': 401, 'error': str(error)})
                ws.send(struct.pack('!H', 1008), 8)
            except OSError: pass
        except (OSError, EOFError, ValueError):
            pass
        finally: finish()

    handler.connection.settimeout(READ_TIMEOUT)
    worker = threading.Thread(target=pump, daemon=True)
    worker.start()
    try:
        while not closed.is_set():
            if ws.receive().get('type') != 'pong':
                raise ValueError('目录连接仅接受心跳回应')
    except (OSError, EOFError, ValueError):
        pass
    finally:
        finish()
        worker.join(2)
