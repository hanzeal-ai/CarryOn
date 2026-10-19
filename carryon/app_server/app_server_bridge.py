"""Bridge for a CarryOn-owned, isolated stdio runtime."""
from carryon.app_server.app_server import AppServer
from carryon.codex_protocol.bridge import ProtocolBridge


class AppServerBridge(ProtocolBridge):
    backend = 'app-server'

    def __init__(self, home, journal):
        super().__init__(home, journal, ipc_factory=AppServer)
