"""Invitation-scoped notifications; credentials are only accepted in the first frame."""
import json
import socket
import threading
import time

from carryon.routes.websocket import WebSocket

HEARTBEAT_INTERVAL = 15
READ_TIMEOUT = 45


def snapshot(server, key, selection):
    kind = selection.get('kind')
    data = selection.get('invitation')
    if selection.get('type') != 'subscribe' or not isinstance(data, dict):
        raise ValueError('确认订阅无效')
    with server.auth_lock:
        server.prune()
        if kind == 'qr-claim':
            entry = server.auth.poll(data)
            result = {'state': entry['state']}
            expires = entry['expires']
        elif kind in ('qr-owner', 'binding'):
            if key is None or server.sessions.get(key, 0) <= time.monotonic():
                raise PermissionError('登录已过期，请重新登录')
            if kind == 'qr-owner':
                result = server.auth.owner_action(data, key, 'status')
                expires = server.auth.entry(data.get('id'))['expires']
            else:
                with server.binding_invites.lock:
                    result = server.binding_invites.inspect(data, server.auth.identity(key))
                    expires = time.monotonic() + max(0, server.binding_invites.entry(data, 'scan')['expires'] - time.time())
        else:
            raise ValueError('确认订阅类型无效')
        return result, expires


def serve(handler, key):
    server = handler.server
    ws = WebSocket(handler)
    closed = threading.Event()

    def finish():
        closed.set()
        with server.directory_changed:server.directory_changed.notify_all()
        try:handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:pass

    def failure(error):
        try:ws.send({'type':'error','error':str(error),'terminal':True})
        except OSError:pass

    try:
        handler.connection.settimeout(5)
        selection = ws.receive()
        snapshot(server, key, selection)  # Validate before admitting a waiting worker.
    except (ValueError, PermissionError) as error:
        failure(error);finish();return
    except (OSError, EOFError):
        finish();return

    def pump():
        revision=-1;signature=None;expires=0
        heartbeat=time.monotonic()+HEARTBEAT_INTERVAL
        try:
            while not closed.is_set() and not server.directory_closed:
                with server.directory_changed:
                    changed=revision!=server.directory_revision
                    revision=server.directory_revision
                # Expiry/session validity is checked at the heartbeat even without mutations.
                if changed or time.monotonic()>=min(expires,heartbeat):
                    result,expires=snapshot(server,key,selection)
                    current=json.dumps(result,sort_keys=True)
                    if current!=signature:
                        ws.send({'type':'confirmation','body':result});signature=current
                if time.monotonic()>=heartbeat:
                    ws.send({'type':'ping'});heartbeat=time.monotonic()+HEARTBEAT_INTERVAL
                timeout=max(0,min(expires,heartbeat)-time.monotonic())
                with server.directory_changed:
                    if revision==server.directory_revision and not closed.is_set() and not server.directory_closed:
                        server.directory_changed.wait(timeout)
        except (PermissionError, ValueError) as error:failure(error)
        except (OSError, EOFError):pass
        finally:finish()

    handler.connection.settimeout(READ_TIMEOUT)
    worker=threading.Thread(target=pump,daemon=True);worker.start()
    try:
        while not closed.is_set():
            if ws.receive().get('type')!='pong':raise ValueError('确认连接仅接受心跳回应')
    except (OSError, EOFError, ValueError):pass
    finally:finish();worker.join(2)
