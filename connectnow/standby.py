"""Opt-in, service-scoped AC sleep assertion. Never changes pmset settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from .paths import save_json


class RemoteStandby:
    def __init__(self, directory):
        self.path = Path(directory) / 'standby.json'
        self.lock = threading.RLock()
        self.process = None
        self.error = None
        self.enabled = False
        if self.path.exists():
            value = json.loads(self.path.read_text()).get('enabled')
            if type(value) is not bool:
                raise ValueError('远程待机配置无效')
            self.enabled = value

    @property
    def supported(self):
        return sys.platform == 'darwin' and Path('/usr/bin/caffeinate').is_file()

    def start(self):
        with self.lock:
            if not self.enabled or self.process is not None and self.process.poll() is None:
                return
            if not self.supported:
                self.error = '远程待机仅支持 macOS'
                return
            try:
                self.process = subprocess.Popen(
                    ['/usr/bin/caffeinate', '-s', '-w', str(os.getpid())],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.error = None
            except OSError:
                self.process = None
                self.error = '无法启动防睡眠保护'

    def close(self):
        with self.lock:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
                self.process = None

    def configure(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled 必须为布尔值')
        with self.lock:
            if enabled and not self.supported:
                raise ValueError('远程待机仅支持 macOS')
            previous = self.enabled
            self.enabled = enabled
            if enabled:
                self.start()
                if self.error:
                    self.enabled = previous
                    raise ValueError(self.error)
            try:
                save_json(self.path, {'enabled': enabled})
            except OSError:
                self.enabled = previous
                if not previous:
                    self.close()
                raise
            if not enabled:
                self.close()
                self.error = None
            return self.status()

    @staticmethod
    def power_source():
        try:
            result = subprocess.run(['/usr/bin/pmset', '-g', 'batt'], capture_output=True,
                                    text=True, timeout=3, check=True)
            first = result.stdout.splitlines()[0] if result.stdout else ''
            if "'AC Power'" in first:
                return 'ac'
            if "'Battery Power'" in first:
                return 'battery'
        except (OSError, subprocess.SubprocessError):
            pass
        return 'unknown'

    def status(self):
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            power = self.power_source() if self.supported else 'unknown'
            error = self.error
            if self.enabled and not running and not error:
                error = '防睡眠进程未运行，请重新开启远程待机'
            return {'enabled': self.enabled, 'supported': self.supported,
                    'running': running, 'powerSource': power,
                    'effective': self.enabled and running and power == 'ac', 'error': error}
