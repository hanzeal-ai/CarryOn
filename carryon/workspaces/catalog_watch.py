"""Read-only catalog invalidation from OS vnode events; never interpret file contents."""
import os
import re
import select
import threading
from pathlib import Path


class CatalogWatch:
    """macOS/BSD kqueue watcher. Unsupported/failed watches explicitly use polling."""
    def __init__(self, home, changed):
        self.home = Path(home)
        self.changed = changed
        self.mode = 'fallback-poll'
        self.error = None
        self.closed = threading.Event()
        self.thread = None
        self.queue = None
        self.files = {}

    @staticmethod
    def relevant(name):
        return name == '.codex-global-state.json' or bool(re.fullmatch(r'state_\d+\.sqlite(?:-wal|-journal)?', name))

    def start(self):
        if not hasattr(select, 'kqueue'):
            self.error = 'kqueue unavailable'
            return
        try:
            self.queue = select.kqueue()
            self._reconcile()
            self.mode = 'filesystem-events'
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        except Exception as exc:
            self._failed(exc)

    def _reconcile(self):
        paths = {self.home, *(p for p in self.home.iterdir() if self.relevant(p.name))}
        for path, (fd, identity) in list(self.files.items()):
            try:
                stat = path.stat()
                current = (stat.st_dev, stat.st_ino)
            except FileNotFoundError:
                current = None
            if path not in paths or current != identity:
                os.close(fd)
                del self.files[path]
        for path in paths - self.files.keys():
            try:
                fd = os.open(path, os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
            except FileNotFoundError:
                if path == self.home:
                    raise
                continue
            try:
                stat = os.fstat(fd)
                flags = select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_ATTRIB | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_REVOKE
                self.queue.control([select.kevent(fd, filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=flags)], 0, 0)
                self.files[path] = (fd, (stat.st_dev, stat.st_ino))
            except BaseException:
                os.close(fd)
                raise

    def _run(self):
        try:
            while not self.closed.is_set():
                events = self.queue.control(None, 128, .5)
                if not events:
                    continue
                if any(event.flags & select.KQ_EV_ERROR for event in events):
                    raise OSError('catalog vnode event error')
                # The home vnode detects newly created WAL files and atomic replacements.
                # Drain bursts with a bounded delay; continuous writes cannot starve readers.
                if self.closed.wait(.15):
                    break
                self._reconcile()
                self.changed()
        except Exception as exc:
            if not self.closed.is_set():
                self._failed(exc)

    def _failed(self, exc):
        self.mode = 'fallback-poll'
        self.error = type(exc).__name__
        self._dispose()
        # The timed fallback must remain active even if notification delivery fails.
        try:
            self.changed()
        except Exception:
            pass

    def _dispose(self):
        for fd, _ in self.files.values():
            os.close(fd)
        self.files.clear()
        if self.queue is not None:
            self.queue.close()
            self.queue = None

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(2)
        self._dispose()
