"""Retire only an Owner whose native archive has been confirmed."""
from carryon.desktop_ipc.ipc import IPCError


def detach(bridge, tid, expected_session):
    """Only a confirmed native archive may retire this Owner; journal and drafts survive."""
    service = bridge.owner_service
    if service is None: return
    with service._thread_lock(tid), service.lock:
        if not bridge.catalog.archive_record(tid)['archived']:
            raise IPCError('原生归档尚未确认，保留 Owner')
        entry = service.entries.get(tid)
        if entry is None: return
        if entry['runtime'].session_id != expected_session:
            raise IPCError('归档 Owner 身份已改变，保留新 Owner 并核对')
        state = entry['runtime'].current(tid)
        if state and state['threadRuntimeStatus']['type'] not in ('idle', 'notLoaded'):
            raise IPCError('归档后原生仍在执行，保留 Owner 并核对')
        entry['conflict'] = True
        try: service.publish(tid, force=True)
        except (OSError, IPCError): pass
        entry['runtime'].close()
        service.entries.pop(tid)
        if not service.entries and not service.loading: service.bus.close()
        service.dirty.set()
