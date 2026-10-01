"""Read/pause/clear a suspended Owner goal without resuming its task."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.history_cache import NativeSnapshot


@contextmanager
def session(bridge, tid, authorize):
    service = bridge.owner_service
    if service is None:
        yield None; return
    with service._thread_lock(tid):
        with service.lock:
            entry = service.entries.get(tid)
            if not entry or not entry.get('suspended'):
                target = False
            else:
                target = True; original = entry['runtime']
                entry['in_flight'] = entry.get('in_flight', 0) + 1
        if not target:
            yield None; return
        runtime = None
        def guard(write):
            with service.lock:
                if (service.closed.is_set() or service.entries.get(tid) is not entry
                        or entry['runtime'] is not original or not entry.get('suspended')
                        or entry['conflict'] or entry['disconnect'] or not service.bus.connected):
                    raise IPCError('目标控制期间会话归属已改变')
                write()
        def project(goal, unknown=False):
            def update():
                if entry['snapshot'] is None: raise IPCError('已暂停会话缺少原生快照')
                previous = entry['snapshot']
                entry['snapshot'] = NativeSnapshot({**deepcopy(previous),
                    'threadGoal': previous.get('threadGoal') if unknown else goal, '_goalUnknown': unknown})
                service.publish(tid, force=True)
            guard(update)
        try:
            authorize()
            runtime = service.prewarm.take()
            yield SimpleNamespace(runtime=runtime, guard=guard, project=project)
        finally:
            if runtime: runtime.close()
            with service.lock: entry['in_flight'] -= 1
            service.dirty.set()
