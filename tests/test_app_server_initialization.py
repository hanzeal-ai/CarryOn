import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from carryon.app_server.initialization import initialization_lock
from carryon.errors import IPCError


class NativeInitializationTests(unittest.TestCase):
    def test_cross_process_exclusion_is_bounded_and_per_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); other = root / 'other'; other.mkdir()
            worker = subprocess.Popen([sys.executable, '-u', '-c',
                'import sys\nfrom pathlib import Path\n'
                'from carryon.app_server.initialization import initialization_lock\n'
                'with initialization_lock(Path(sys.argv[1])):\n'
                ' print("locked", flush=True)\n sys.stdin.readline()\n', str(root)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(worker.stdout.readline().strip(), 'locked')
                before = time.monotonic()
                with self.assertRaises(IPCError):
                    with initialization_lock(root, timeout=.1): self.fail('cross-process lock bypassed')
                self.assertLess(time.monotonic() - before, 2)
                with initialization_lock(other, timeout=.1): pass
                worker.communicate('\n', timeout=5)
                self.assertEqual(worker.returncode, 0)
                with initialization_lock(root, timeout=.1): pass
            finally:
                if worker.poll() is None: worker.kill()
                worker.communicate()

    def test_failure_releases_initialization_without_replaying(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); writes = []
            with self.assertRaises(ValueError):
                with initialization_lock(home):
                    writes.append('initialize')
                    raise ValueError('native failure')
            with initialization_lock(home, timeout=.1): pass
            self.assertEqual(writes, ['initialize'])
