import base64
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from carryon.sessions import reference_icons


def png(width=16, height=16):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\0' + b'\0\x80\xff\xff' * width) * height)) + chunk(b'IEND', b'')


class ReferenceIconsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.skill = self.root / 'skill'
        self.skill.mkdir()
        (self.skill / 'SKILL.md').write_text('fixture')
        self.icon = self.skill / 'small.png'
        self.icon.write_bytes(png())
        self.row = {'name': 'fixture', 'path': str(self.skill / 'SKILL.md'), 'enabled': True, 'interface': {'iconSmall': str(self.icon)}}

    def test_native_icon_is_presentation_and_does_not_mutate_catalog(self):
        projected = reference_icons.skill_icons([self.row])[0]
        self.assertEqual(base64.b64decode(projected['iconData']), png())
        self.assertNotIn('iconData', self.row)
        self.assertEqual(projected['name'], self.row['name'])
        self.assertEqual(projected['interface'], self.row['interface'])

    def test_outside_skill_directory_and_symlink_escape_are_not_read(self):
        outside = self.root / 'outside.png'
        outside.write_bytes(png())
        self.row['interface']['iconSmall'] = str(outside)
        self.assertNotIn('iconData', reference_icons.skill_icons([self.row])[0])
        self.icon.unlink(); self.icon.symlink_to(outside)
        self.row['interface']['iconSmall'] = str(self.icon)
        self.assertNotIn('iconData', reference_icons.skill_icons([self.row])[0])

    def test_unsupported_corrupt_oversized_and_large_dimensions_use_generic_icon(self):
        for data in [b'<svg/>', b'\x89PNG', png(513, 1), png() + b'x' * reference_icons.MAX_ICON_BYTES]:
            self.icon.write_bytes(data)
            self.assertNotIn('iconData', reference_icons.skill_icons([self.row])[0])
        self.icon.unlink()
        self.assertNotIn('iconData', reference_icons.skill_icons([self.row])[0])

    def test_catalog_has_a_total_byte_budget(self):
        with patch.object(reference_icons, 'MAX_CATALOG_ICON_BYTES', len(png())):
            rows = reference_icons.skill_icons([self.row, self.row])
        self.assertIn('iconData', rows[0]); self.assertNotIn('iconData', rows[1])

    def test_opened_directory_walk_rejects_symlinks(self):
        outside = self.root / 'outside'
        outside.mkdir(); (outside / 'small.png').write_bytes(png())
        (self.skill / 'assets').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            reference_icons._read_icon(self.skill, Path('assets/small.png'), 65536)

    def test_root_ancestor_replacement_is_rejected(self):
        allowed = self.root / 'allowed'; allowed.mkdir()
        root = allowed / 'skill'; root.mkdir(); (root / 'icon.png').write_bytes(png())
        outside = self.root / 'outside'; outside.mkdir()
        other_skill = outside / 'skill'; other_skill.mkdir(); (other_skill / 'icon.png').write_bytes(png())
        allowed.rename(self.root / 'moved')
        allowed.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            reference_icons._read_icon(root, Path('icon.png'), 65536)

    def test_rejected_images_consume_read_budget(self):
        self.icon.write_bytes(b'x' * len(png()))
        with patch.object(reference_icons, 'MAX_CATALOG_ICON_BYTES', len(png())), patch.object(reference_icons, '_read_icon', wraps=reference_icons._read_icon) as read:
            rows = reference_icons.skill_icons([self.row, self.row])
        self.assertEqual(read.call_count, 1)
        self.assertTrue(all('iconData' not in row for row in rows))

    def test_send_inventory_never_loads_images(self):
        from carryon.sessions import skills
        from types import SimpleNamespace
        runtime = SimpleNamespace(process=object(), session_id='fixture', connected=True,
                                  current=lambda tid: {'cwd': str(self.skill)},
                                  rpc=lambda method, params: {'data': [{'cwd': str(self.skill), 'skills': [self.row], 'errors': []}]})
        with patch.object(skills, 'skill_icons', side_effect=AssertionError('send must not read icons')):
            rows, identity = skills.inventory(runtime, 'fixture')
        self.assertEqual(rows['skills'], [self.row])
