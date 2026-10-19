"""Short native read control, independent of session execution and feature routing."""
from contextlib import contextmanager
from carryon.errors import IPCError


@contextmanager
def reader(bridge):
    ipc, generation = bridge.require()
    service = None
    if getattr(ipc, 'protocol', None) == 'codex-app-server':
        runtime = ipc
    elif hasattr(bridge, 'owners'):
        service = bridge.owners()
        runtime = service.prewarm.take()
    else:
        raise IPCError('当前连接不支持原生历史读取')
    identity = runtime.connection_identity
    def verify():
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if not runtime.connected or runtime.connection_identity != identity:
                raise IPCError('读取期间原生连接已改变')
            if service is not None and (getattr(bridge, 'owner_service', None) is not service or service.closed.is_set()):
                raise IPCError('读取期间工作区归属已改变')
    try:
        verify()
        yield runtime, verify
    finally:
        if service is not None: runtime.close()
