"""Application errors shared by transports and bridge operations."""


class BridgeError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class IPCError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain
