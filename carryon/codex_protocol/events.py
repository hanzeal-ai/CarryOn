"""Common projection invalidation state; no desktop wire semantics."""


class ProjectionEvents:
    def __init__(self):
        self.queues = {}
        self.flags = {}
        self.catalog_revision = 0
        self.reset_revision = 0

    def clear(self):
        self.queues.clear()
        self.flags.clear()
        self.catalog_revision += 1
