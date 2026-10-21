#!/usr/bin/env python3
"""Check the actual delivery artifact without contacting or changing a host."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from receive import validate_wheel


def check_wheel(path):
    data = path.read_bytes()
    if len(data) > 10 * 1024 * 1024:
        raise ValueError('Upload too large')
    with validate_wheel(data) as archive, tempfile.TemporaryDirectory() as directory:
        archive.extractall(directory)
        for module in ('carryon.cloud.gateway', 'carryon.cloud.console'):
            # Ignore PYTHONPATH and installed packages; CarryOn uses only stdlib.
            # cwd is the extracted wheel, not the source tree.
            result = subprocess.run(
                [sys.executable, '-E', '-S', '-B', '-m', module, 'serve', '--help'],
                cwd=directory, capture_output=True, text=True, timeout=15)
            if result.returncode or '--config' not in result.stdout:
                raise ValueError('Wheel entrypoint check failed for '+module+': '+result.stderr)
    print('Wheel deployment checks passed: '+path.name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    args = parser.parse_args()
    check_wheel(args.wheel)
