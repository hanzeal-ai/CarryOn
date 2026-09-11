"""Bounded RFC 6455 text stream for the loopback UI; mutations stay on HTTP."""
import base64
import hashlib
import hmac
import json
import logging
import os
import socket
import struct
import threading

from .errors import BridgeError


class WebSocket:
    MAX_MESSAGE = 100000

    def __init__(self, handler, client=False):
        self.handler = handler
        self.client = client
        self.lock = threading.Lock()

    def send(self, data, opcode=1):
        payload = json.dumps(data, ensure_ascii=False).encode() if opcode == 1 else data
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError('WebSocket response too large')
        size = len(payload)
        header = bytes([0x80 | opcode])
        header += bytes([size]) if size < 126 else (b'\x7e' + struct.pack('!H', size) if size < 65536 else b'\x7f' + struct.pack('!Q', size))
        if self.client:
            header = header[:1] + bytes([header[1] | 128]) + header[2:]
            mask = os.urandom(4)
            header += mask
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        with self.lock:
            self.handler.connection.sendall(header + payload)

    def exact(self, size):
        data = self.handler.rfile.read(size)
        if len(data) != size:
            raise EOFError()
        return data

    def receive(self):
        fragments = bytearray()
        active = False
        while True:
            a, b = self.exact(2)
            final, opcode = bool(a & 128), a & 15
            size = b & 127
            if a & 112 or bool(b & 128) == self.client or opcode not in (0, 1, 8, 9, 10):
                raise ValueError('Invalid WebSocket frame')
            if size == 126:
                size = struct.unpack('!H', self.exact(2))[0]
                if size < 126: raise ValueError('Invalid frame length')
            elif size == 127:
                size = struct.unpack('!Q', self.exact(8))[0]
                if size < 65536: raise ValueError('Invalid frame length')
            if opcode >= 8 and (not final or size > 125):
                raise ValueError('Invalid control frame')
            if size + len(fragments) > self.MAX_MESSAGE:
                raise ValueError('WebSocket request too large')
            mask = self.exact(4) if not self.client else None
            payload = self.exact(size)
            if mask: payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
            if opcode == 8:
                if len(payload) == 1: raise ValueError('Invalid close frame')
                self.send(payload, 8)
                raise EOFError()
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode == 10:
                continue
            if (opcode == 0 and not active) or (opcode == 1 and active):
                raise ValueError('Invalid continuation')
            active = True
            fragments.extend(payload)
            if final:
                message = json.loads(fragments.decode('utf-8'))
                if not isinstance(message, dict): raise ValueError('Expected object')
                return message


def upgrade(handler):
    headers = handler.headers
    if (headers.get('Upgrade', '').lower() != 'websocket'
            or 'upgrade' not in [v.strip().lower() for v in headers.get('Connection', '').split(',')]
            or headers.get('Sec-WebSocket-Version') != '13'):
        raise ValueError('Invalid WebSocket handshake')
    key = headers.get('Sec-WebSocket-Key', '')
    if len(base64.b64decode(key, validate=True)) != 16:
        raise ValueError('Invalid WebSocket key')
    accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
    handler.send_response(101)
    handler.send_header('Upgrade', 'websocket')
    handler.send_header('Connection', 'Upgrade')
    handler.send_header('Sec-WebSocket-Accept', accept)
    handler.end_headers()
    handler.wfile.flush()
    handler.close_connection = True


def serve(handler):
    """Authenticate and transport Bridge projections; no native or job policy here."""
    ws = WebSocket(handler)
    closed = threading.Event()
    session = None
    thread = None

    def writer():
        revision, previous = -1, None

        def send(packet):
            nonlocal previous
            signature = json.dumps(packet, ensure_ascii=False)
            if signature != previous:
                ws.send(packet)
                previous = signature
            else:
                ws.send(b'heartbeat', 9)

        try:
            while not closed.is_set():
                revision = session.wait(revision)
                if closed.is_set():
                    break
                session.deliver(session.update(), send)
        except Exception as exc:
            if not isinstance(exc, (OSError, EOFError, ValueError, BridgeError)):
                logging.getLogger(__name__).error('Stream failed (%s)', type(exc).__name__)
        finally:
            closed.set()
            session.close()
            try:
                handler.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    try:
        handler.connection.settimeout(5)
        auth = ws.receive()
        if auth.get('type') != 'auth' or not isinstance(auth.get('token'), str) or not hmac.compare_digest(auth['token'], handler.server.token):
            ws.send(struct.pack('!H', 1008) + b'Unauthorized', 8)
            return
        handler.connection.settimeout(45)
        session = handler.server.bridge.open_stream()
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        while not closed.is_set():
            session.subscribe(ws.receive())
    except (OSError, EOFError, ValueError):
        pass
    finally:
        closed.set()
        if session:
            session.close()
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if thread:
            thread.join(2)
