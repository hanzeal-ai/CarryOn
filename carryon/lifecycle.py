"""Keep a requested local bridge connected; explicit off cancels reconnects."""
import threading

from .errors import BridgeError
from .ipc import IPCError


class BridgeLifecycle:
    def __init__(self, bridge):
        self.bridge = bridge
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.requested = False
        self.error = None
        self.worker = threading.Thread(target=self.run, daemon=True, name='codex-connection')

    def start(self):
        self.worker.start()

    def configure(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled 必须为布尔值')
        with self.lock:
            self.requested = enabled
            if enabled:
                self.connect()
            else:
                self.error = None
                self.bridge.disable()
            return self.status()

    def connect(self):
        try:
            if not self.bridge.status()['enabled']:
                self.bridge.disable()
                self.bridge.enable()
            self.error = None
        except (BridgeError, IPCError, OSError) as exc:
            self.error = str(exc)

    def status(self):
        with self.lock:
            active = self.bridge.status()['enabled']
            return {**self.bridge.status(), 'requested': self.requested,
                    'connectionState': 'connected' if active else 'waiting' if self.requested else 'stopped',
                    'connectionError': self.error}

    def run(self):
        while not self.closed.wait(2):
            with self.lock:
                if self.requested:
                    self.connect()

    def close(self):
        self.closed.set()
        if self.worker.ident is not None:
            self.worker.join(5)
        with self.lock:
            self.requested = False
            self.bridge.disable()
