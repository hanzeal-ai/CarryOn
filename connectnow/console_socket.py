"""Cookie-authorized console WebSocket; subscriptions can change on one connection."""
import socket
import struct
import threading
import time
import uuid

from .gateway import Offline, Uncertain
from .websocket import WebSocket

HEARTBEAT_INTERVAL = 15
READ_TIMEOUT = 45


def serve(handler, session_key, device_id):
    server = handler.server
    ws = WebSocket(handler)
    closed = threading.Event()
    device = None
    writer = None
    active = None  # (device stream ID, client subscription ID)
    selection_lock = threading.Lock()

    def send(payload):
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

    def release(context):
        if context is not None:
            server.release_stream(context[0])
            with device.lock:
                device.streams.pop(context[0], None)
                device.lock.notify_all()

    def subscribe(selection):
        nonlocal active
        if selection.get('type') != 'subscribe' or not isinstance(selection.get('subscription'), str) or not 1 <= len(selection['subscription']) <= 100:
            raise ValueError('订阅参数无效')
        with selection_lock:
            previous, active = active, None
        release(previous)
        sid = uuid.uuid4().hex
        with server.auth_lock, server.lock:
            if server.sessions.get(session_key, 0) <= time.monotonic():
                raise PermissionError('登录已过期，请重新登录')
            if device_id not in server.config['devices'] or server.devices.get(device_id) is not device or device.closed:
                raise Offline()
            with device.lock:
                if len(device.streams) >= 8:
                    raise ValueError('最多 8 个订阅，请关闭不再使用的会话')
                device.streams[sid] = {'revision': 0, 'body': None}
            server.console_streams[sid] = {'device': device_id, 'session': session_key, 'last': time.monotonic()}
        context = (sid, selection['subscription'], selection.get('historyProtocol') == 1)
        try:
            response = device.call({'type': 'subscribe', 'streamId': sid, 'selection': {**selection, 'historyWire': 1}})
            if response['status'] != 200:
                send({'type': 'error', 'status': response['status'], 'error': (response.get('body') or {}).get('error', '订阅失败')})
                raise ValueError('订阅失败')
            with selection_lock:
                active = context
            with device.lock:
                device.lock.notify_all()
        except BaseException:
            release(context)
            raise

    def pump():
        from .history_wire import HistoryWire
        wire = HistoryWire()
        seen = None
        revision = delivery_revision = 0
        last_ping = time.monotonic()
        try:
            while not closed.is_set():
                with selection_lock:
                    context = active
                packet = None
                if context is not None:
                    if context != seen:
                        seen, revision = context, 0
                    with device.lock:
                        if device.closed:
                            raise Offline()
                        record = device.streams.get(context[0])
                        if record and record['revision'] <= revision:
                            device.lock.wait(min(1, HEARTBEAT_INTERVAL))
                        record = device.streams.get(context[0])
                        if record:
                            packet = dict(record)
                    with selection_lock:
                        if active != context:
                            continue
                        # Keep selection stable until its registration is checked.
                        # Releasing the previous stream is a normal selection change.
                        with server.auth_lock:
                            entry = server.console_streams.get(context[0])
                            if entry is None:
                                raise PermissionError('订阅已失效')
                            entry['last'] = time.monotonic()
                    if packet and packet['revision'] > revision and isinstance(packet['body'], dict):
                        delivery_revision += 1
                        body = {**packet['body'], 'subscription': context[1]}
                        send({'type': 'update', 'revision': delivery_revision, 'subscription': context[1],
                              'resubscribe': True,
                              'body': wire.encode(body) if context[2] else body})
                        revision = packet['revision']
                else:
                    closed.wait(min(.1, HEARTBEAT_INTERVAL))
                now = time.monotonic()
                if now - last_ping >= HEARTBEAT_INTERVAL:
                    send({'type': 'ping'}); last_ping = now
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
        with server.auth_lock, server.lock:
            if server.sessions.get(session_key, 0) <= time.monotonic():
                raise PermissionError('登录已过期，请重新登录')
            device = server.devices.get(device_id)
            if device_id not in server.config['devices'] or device is None or device.closed:
                raise Offline()
        handler.connection.settimeout(READ_TIMEOUT)
        writer = threading.Thread(target=pump, daemon=True)
        writer.start()
        subscribe(selection)
        while not closed.is_set():
            message = ws.receive()
            if message.get('type') == 'subscribe':
                subscribe(message)
            elif message.get('type') != 'pong':
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
        with selection_lock:
            previous, active = active, None
        release(previous)
        if writer:
            writer.join(2)
