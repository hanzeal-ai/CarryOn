"""One bounded, observable full refresh per workspace; never resumes a task."""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from carryon.desktop_ipc.ipc import IPCError


class WorkspaceSync:
    def __init__(self, workspace):
        self.workspace = workspace
        self.lock = threading.RLock()
        self.worker = None
        self.result = None
        self.results = {}

    def start(self):
        with self.lock:
            if self.workspace.closed.is_set():raise ValueError('工作区已关闭')
            if self.worker is not None and self.worker.is_alive():
                return dict(self.result)
            self.result = {'id': str(uuid.uuid4()), 'state': 'running', 'completed': 0, 'total': 0}
            self.results[self.result['id']] = self.result
            while len(self.results)>8:self.results.pop(next(iter(self.results)))
            self.worker = threading.Thread(target=self._run, daemon=True, name='workspace-refresh')
            self.worker.start()
            return dict(self.result)

    def poll(self, identity):
        with self.lock:
            if identity not in self.results:
                raise ValueError('同步记录已失效，请重新下拉刷新')
            return dict(self.results[identity])

    def close(self):
        if self.worker:self.worker.join(5)

    def _run(self):
        workspace = self.workspace
        bridge = workspace.bridge
        try:
            ipc, generation = bridge.require()
            cutoffs = workspace.read_cutoffs()
            workspace.catalog_refresh()
            if bridge.realtime:bridge.realtime.sync_watches()
            ids = sorted(workspace.thread_ids())
            for tid in ids:cutoffs.setdefault(tid,0)
            with self.lock:self.result['total'] = len(ids)
            failures = 0
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix='workspace-refresh-state') as pool:
                # Bounded batches also bound outstanding work when disconnected.
                for offset in range(0, len(ids), 4):
                    if workspace.closed.is_set():raise ValueError('工作区已关闭')
                    bridge.check_generation(ipc, generation)
                    for future in as_completed([pool.submit(self._thread, ipc, generation, tid) for tid in ids[offset:offset+4]]):
                        failures += not future.result()
                        with self.lock:self.result['completed'] += 1
            if workspace.closed.is_set():raise ValueError('工作区已关闭')
            read_pending=workspace.sync_desktop_reads(ipc, generation, cutoffs)
            with bridge.lock:
                bridge.check_generation(ipc, generation)
                workspace.invalidate_status()
            with self.lock:
                self.result['state'] = 'failed' if failures or read_pending else 'completed'
                self.result['readPending'] = read_pending
                if read_pending:self.result['error'] = f'{read_pending} 个会话的桌面已读状态尚无法确认，请在桌面端确认后重试'
                if failures:self.result['error'] = f'{failures} 个会话未能同步，请重试'
        except Exception as error:
            with self.lock:
                self.result['state'] = 'failed'
                self.result['error'] = str(error) if isinstance(error, (ValueError, IPCError)) else '工作区同步失败，请重试'
        finally:
            bridge.notify()

    def _thread(self, ipc, generation, tid):
        workspace = self.workspace
        bridge = workspace.bridge
        status = None
        try:
            # refresh_snapshot bypasses the sidebar cache without waking/resuming.
            ipc.refresh_snapshot(tid)
        except (IPCError, OSError, ValueError) as error:
            status = ({'state': 'notLoaded', 'label': '未加载'} if str(error) == 'no-client-found'
                      else {'state': 'unknown', 'label': '同步失败'})
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if workspace.closed.is_set():return False
            realtime = bridge.realtime
            if realtime:
                realtime.unavailable[tid] = (ipc, time.monotonic(), status)
            native = ipc.current(tid)
            if status is None and native is not None:
                workspace.observe(native)
            workspace.invalidate_status()
        return status is None or status['state'] == 'notLoaded'
