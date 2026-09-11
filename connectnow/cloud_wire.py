"""Outbound TLS WebSocket handshake using the existing bounded frame codec."""
import base64
import hashlib
import os
import socket
import ssl
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit
from .websocket import WebSocket


def endpoint(url, dev_local=False):
    if not isinstance(url,str) or any(c.isspace() for c in url):raise ValueError('云端地址无效')
    parsed=urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError('云端地址不能携带凭证、查询参数或片段')
    if not parsed.hostname:raise ValueError('云端地址缺少主机')
    if parsed.scheme!='wss' and not (dev_local and parsed.scheme=='ws' and parsed.hostname in ('127.0.0.1','localhost','::1')):
        raise ValueError('云端地址必须使用 wss://；--dev-local 仅允许本机 ws://')
    return parsed


def tls_context():
    context=ssl.create_default_context()
    # Bundled Python must not depend on Homebrew certificate paths on the target Mac.
    if sys.platform=="darwin" and not context.get_ca_certs():
        roots=subprocess.run(["/usr/bin/security","find-certificate","-a","-p",
            "/System/Library/Keychains/SystemRootCertificates.keychain"],
            check=True,capture_output=True,text=True,timeout=10)
        context.load_verify_locations(cadata=roots.stdout)
    return context


def connect(url, dev_local=False):
    parsed=endpoint(url,dev_local)
    port=parsed.port or (443 if parsed.scheme=='wss' else 80)
    sock=socket.create_connection((parsed.hostname,port),timeout=10)
    stream=None
    try:
        if parsed.scheme=='wss': sock=tls_context().wrap_socket(sock,server_hostname=parsed.hostname)
        stream=sock.makefile('rb')
        key=base64.b64encode(os.urandom(16)).decode()
        host=('['+parsed.hostname+']' if ':' in parsed.hostname else parsed.hostname)+':'+str(port)
        request=f'GET {parsed.path or "/"} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n'
        sock.sendall(request.encode('ascii'))
        status=stream.readline(4096)
        if not status.startswith(b'HTTP/1.1 101 ') and not status.startswith(b'HTTP/1.0 101 '):
            raise ValueError('云端拒绝 WebSocket 握手')
        headers={};total=len(status)
        while True:
            line=stream.readline(4096);total+=len(line)
            if total>16384 or not line:raise ValueError('云端握手头无效')
            if line==b'\r\n':break
            name,value=line.decode('ascii').split(':',1);headers[name.lower()]=value.strip()
        expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if (headers.get('sec-websocket-accept')!=expected or headers.get('upgrade','').lower()!='websocket'
                or 'upgrade' not in [part.strip().lower() for part in headers.get('connection','').split(',')]):
            raise ValueError('云端 WebSocket 握手不匹配')
        sock.settimeout(45)
        ws=WebSocket(SimpleNamespace(connection=sock,rfile=stream),client=True)
        from .images import MAX_REQUEST_BYTES
        ws.MAX_MESSAGE=MAX_REQUEST_BYTES+4096
        return ws
    except BaseException:
        if stream:stream.close()
        sock.close();raise


def close(ws):
    try:ws.handler.connection.shutdown(socket.SHUT_RDWR)
    except OSError:pass
    ws.handler.connection.close()
    ws.handler.rfile.close()
