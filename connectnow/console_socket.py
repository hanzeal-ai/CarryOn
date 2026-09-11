"""Cookie-authorized console WebSocket; device projections remain authoritative."""
import socket
import struct
import threading
import time
import uuid

from .gateway import Offline, Uncertain
from .websocket import WebSocket


def serve(handler, session_key, device_id):
    server = handler.server
    ws = WebSocket(handler)
    closed = threading.Event()
    stream_id = uuid.uuid4().hex
    device = None
    writer = None

    def send(payload):
        # Recheck authority before every delivery; never hold global locks during socket I/O.
        with server.auth_lock, server.lock:
            if server.sessions.get(session_key, 0) <= time.monotonic():
                raise PermissionError('登录已过期，请重新登录')
            if device_id not in server.config['devices'] or server.devices.get(device_id) is not device:
                raise Offline()
        ws.send(payload)

    def finish():
        closed.set()
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if device is not None:
            with device.lock:
                device.lock.notify_all()

    def pump(subscription):
        revision = 0
        last_sent = time.monotonic()
        try:
            while not closed.is_set():
                with device.lock:
                    record = device.streams.get(stream_id)
                    if record and record['revision'] <= revision and not device.closed:
                        device.lock.wait(1)
                    if closed.is_set():
                        break
                    if device.closed:
                        raise Offline()
                    record = device.streams.get(stream_id)
                    if record is None:
                        raise PermissionError('订阅已失效')
                    packet = dict(record)
                now = time.monotonic()
                with server.auth_lock:
                    if server.sessions.get(session_key, 0) <= now:
                        raise PermissionError('登录已过期，请重新登录')
                    entry = server.console_streams.get(stream_id)
                    if entry is None:
                        raise PermissionError('订阅已失效')
                    entry['last'] = now
                if packet['revision'] > revision and isinstance(packet['body'], dict):
                    send({'type': 'update', 'revision': packet['revision'], 'subscription': subscription,
                          'body': {**packet['body'], 'subscription': subscription}})
                    revision = packet['revision']; last_sent = now
                elif now - last_sent >= 15:
                    send({'type': 'ping'}); last_sent = now
        except PermissionError as exc:
            try:
                ws.send({'type': 'error', 'status': 401, 'error': str(exc)})
                ws.send(struct.pack('!H', 1008), 8)
            except OSError:
                pass
        except (Offline, OSError, EOFError, ValueError):
            pass
        finally:
            finish()

    try:
        handler.connection.settimeout(5)
        selection = ws.receive()
        if selection.get('type') != 'subscribe' or not isinstance(selection.get('subscription'), str) or not 1 <= len(selection['subscription']) <= 100:
            raise ValueError('订阅参数无效')
        with server.auth_lock, server.lock:
            if server.sessions.get(session_key, 0) <= time.monotonic():
                raise PermissionError('登录已过期，请重新登录')
            device = server.devices.get(device_id)
            if device_id not in server.config['devices'] or device is None or device.closed:
                raise Offline()
            with device.lock:
                if len(device.streams) >= 8:
                    raise ValueError('最多 8 个订阅，请关闭不再使用的会话')
                device.streams[stream_id] = {'revision': 0, 'body': None}
            server.console_streams[stream_id] = {'device': device_id, 'session': session_key, 'last': time.monotonic()}
        response = device.call({'type': 'subscribe', 'streamId': stream_id, 'selection': selection})
        if response['status'] != 200:
            send({'type': 'error', 'status': response['status'], 'error': (response.get('body') or {}).get('error', '订阅失败')})
            return
        handler.connection.settimeout(45)
        writer = threading.Thread(target=pump, args=(selection['subscription'],), daemon=True)
        writer.start()
        while not closed.is_set():
            if ws.receive().get('type') != 'pong':
                raise ValueError('此连接仅用于订阅实时更新，提交操作请使用 HTTP')
    except (ValueError, PermissionError, Offline, Uncertain) as exc:
        try:
            ws.send({'type': 'error', 'status': 401 if isinstance(exc, PermissionError) else 503 if isinstance(exc, (Offline, Uncertain)) else 400,
                     'error': str(exc) or '设备离线，请重新连接'})
        except OSError:
            pass
    except (OSError, EOFError):
        pass
    finally:
        finish()
        server.release_stream(stream_id)
        # A replaced/revoked device may no longer be in the server registry.
        if device is not None:
            with device.lock:
                device.streams.pop(stream_id, None)
        if writer:
            writer.join(2)
