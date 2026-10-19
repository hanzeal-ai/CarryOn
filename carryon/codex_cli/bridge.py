"""CLI workspace binding, independent of desktop IPC and owned app-server."""
from carryon.codex_cli.client import CliClient, endpoint
from carryon.codex_protocol.bridge import ProtocolBridge
from carryon.errors import BridgeError, IPCError


class CliBridge(ProtocolBridge):
    backend = 'codex-cli'

    def __init__(self, home, journal, *, socket_path=None):
        self.endpoint = endpoint(home, socket_path)
        self.restore_errors = {}
        self.restore_targets = set()
        super().__init__(home, journal, ipc_factory=lambda home: CliClient(home, socket_path=self.endpoint))

    def status(self):
        return {**super().status(), 'cliSocket': str(self.endpoint), 'restoreErrors': dict(self.restore_errors), 'restorePending': bool(self.restore_targets)}

    def enable(self):
        try: return super().enable()
        except BridgeError as exc:
            raise BridgeError('无法连接 Codex CLI；请启动使用同一 CODEX_HOME 的 daemon，或检查配置的 Unix socket：' + str(self.endpoint) + '；' + str(exc), 503) from exc

    def disable(self):
        self.restore_targets.clear()
        self.restore_errors.clear()
        return super().disable()

    def history(self, thread_id, limit=None):
        ipc, generation = self.require()
        ipc.sidebar_snapshot(thread_id)
        with self.lock: self.check_generation(ipc, generation)
        return super().history(thread_id, limit)

    def reconnect(self):
        with self.lock:
            targets = self.restore_targets
            if not (self.enabled and self.ipc and self.ipc.connected):
                if self.ipc:
                    targets.update(self.ipc.restore_threads)
                    targets.update(self.ipc.following)
                super().disable()
                self.enable()
            self.restore_errors = {}
            for tid in list(targets):
                try: self.ipc.sidebar_snapshot(tid)
                except (IPCError, OSError, ValueError) as exc: self.restore_errors[tid] = str(exc)
            self.restore_targets = set(self.restore_errors)
            self.notify()
            return self.status()
