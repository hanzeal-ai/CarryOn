"""Bridge for a CarryOn-owned, isolated stdio runtime."""
from carryon.app_server.app_server import AppServer
from carryon.codex_protocol.bridge import ProtocolBridge
from functools import partial


class AppServerBridge(ProtocolBridge):
    backend = 'app-server'

    def __init__(self, home, journal):
        super().__init__(home, journal, ipc_factory=partial(AppServer, shared_account=True))
