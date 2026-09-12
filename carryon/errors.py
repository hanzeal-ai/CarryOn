"""Application errors shared by transports and bridge operations."""


class BridgeError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status
