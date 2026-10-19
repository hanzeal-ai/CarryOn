"""Serialize native SQLite initialization, without serializing running writers."""
from contextlib import contextmanager
import fcntl
import time

from carryon.errors import IPCError


@contextmanager
def initialization_lock(home, timeout=20):
    with (home / '.carryon-initialize.lock').open('a+') as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise IPCError('工作区原生初始化锁等待超时；尚未启动新进程')
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
