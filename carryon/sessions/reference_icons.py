"""Bounded raster presentation from native skill metadata; never input identity."""
import base64
import os
import struct
import stat
from pathlib import Path

MAX_ICON_BYTES = 65536
MAX_CATALOG_ICON_BYTES = 524288


def _read_icon(root, relative, limit):
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (*root.parts[1:], *relative.parts[:-1]):
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode): return b'', False
            data = handle.read(limit)
            return data, info.st_size <= limit and len(data) == info.st_size
    finally:
        os.close(directory)


def skill_icons(skills):
    budget = MAX_CATALOG_ICON_BYTES
    result = []
    for skill in skills:
        row = dict(skill)
        interface = row.get('interface') or {}
        source = interface.get('iconSmall')
        if isinstance(source, str) and isinstance(row.get('path'), str) and budget:
            try:
                root = Path(row['path']).resolve(strict=True).parent
                icon = Path(source).resolve(strict=True)
                if icon.is_relative_to(root) and icon.is_file():
                    data, complete = _read_icon(root, icon.relative_to(root), min(MAX_ICON_BYTES + 1, budget))
                    budget -= len(data)
                    if complete and len(data) <= MAX_ICON_BYTES and len(data) >= 33 and data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR':
                        width, height = struct.unpack('>II', data[16:24])
                        if 0 < width <= 512 and 0 < height <= 512:
                            row['iconData'] = base64.b64encode(data).decode('ascii')
            except (OSError, ValueError, RuntimeError):
                pass
        result.append(row)
    return result
