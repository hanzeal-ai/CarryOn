"""Hold an existing Owner during metadata control without resuming its task."""
from contextlib import contextmanager
from carryon.desktop_ipc.ipc import IPCError


@contextmanager
def session(bridge, tid, *, loaded_only=False):
    service = bridge.owners()
    with service._thread_lock(tid):
        with service.lock:
            entry = service.entries.get(tid)
            if (not entry or entry['conflict'] or entry['disconnect']
                    or service.closed.is_set() or not service.bus.connected):
                raise IPCError('请先将会话加载到 CarryOn')
            if loaded_only and (entry.get('suspended') or not entry['runtime'].connected):
                raise IPCError('后台终端需要实际拥有会话的原生进程')
            original = entry['runtime']; suspended = entry.get('suspended', False)
            runtime = None
            entry['in_flight'] = entry.get('in_flight', 0) + 1
        try:
            runtime = service.prewarm.take() if suspended else original
        except Exception:
            with service.lock: entry['in_flight'] -= 1
            raise
        def state():
            return entry.get('snapshot') if suspended else runtime.current(tid)
        def guard(write):
            with service.lock:
                if (getattr(bridge, 'owner_service', None) is not service or service.closed.is_set() or service.entries.get(tid) is not entry
                        or entry['runtime'] is not original or entry.get('suspended', False) != suspended or entry['conflict'] or entry['disconnect']
                        or not service.bus.connected or not runtime.connected):
                    raise IPCError('操作期间会话归属已改变')
                write()
        try:
            yield runtime, guard, state, suspended, original.session_id
        finally:
            if suspended: runtime.close()
            with service.lock: entry['in_flight'] -= 1
            service.dirty.set()
