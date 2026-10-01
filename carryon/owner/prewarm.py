"""One initialized, never-loaded runtime reserved for the next owner acquisition."""
import threading
import uuid
from pathlib import Path

from carryon.desktop_ipc.ipc import IPCError


class PrewarmedRuntime:
    def __init__(self, home, directory, factory):
        self.home, self.directory, self.factory = home, Path(directory), factory
        self.condition = threading.Condition()
        self.runtime = None
        self.worker = None
        self.error = None
        self.closed = False

    def start(self):
        with self.condition:
            if self.closed or self.runtime is not None or self.worker is not None:
                return
            self.error = None
            self.worker = threading.Thread(target=self._prepare, daemon=True, name='owner-prewarm')
            try:
                self.worker.start()
            except RuntimeError as exc:
                self.worker = None
                self.error = str(exc)
                self.condition.notify_all()

    def _prepare(self):
        runtime = None
        try:
            runtime = self.factory(self.home, runtime_directory=self.directory / uuid.uuid4().hex)
            runtime.connect()
            with self.condition:
                if not self.closed:
                    self.runtime = runtime
                    runtime = None
        except Exception as exc:
            with self.condition:
                self.error = str(exc)
        finally:
            if runtime is not None:
                runtime.close()
            with self.condition:
                self.worker = None
                self.condition.notify_all()

    def take(self):
        with self.condition:
            if self.error:
                error, self.error = self.error, None
                raise IPCError('app-server prewarm failed: ' + error)
            self.start()
            while self.worker is not None and not self.closed:
                self.condition.wait()
            if self.closed:
                raise IPCError('owner-service-closed')
            if self.error:
                error, self.error = self.error, None
                raise IPCError('app-server prewarm failed: ' + error)
            runtime, self.runtime = self.runtime, None
            if runtime is None:
                raise IPCError('app-server prewarm unavailable')
            self.start()
        if not runtime.connected:
            runtime.close()
            raise IPCError('prewarmed app-server disconnected')
        return runtime

    def close(self):
        with self.condition:
            self.closed = True
            runtime, self.runtime = self.runtime, None
            worker = self.worker
            self.condition.notify_all()
        if runtime is not None:
            runtime.close()
        # Initialization RPCs are bounded. Join ensures a late-starting process
        # is closed before service exit, even if shutdown raced with connect().
        if worker is not None and worker is not threading.current_thread():
            worker.join()
