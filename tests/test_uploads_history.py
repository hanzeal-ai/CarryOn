"""History advertises only the attachment reads supported by the existing API."""
import tempfile
import unittest
from pathlib import Path

from carryon.errors import BridgeError
from carryon.sessions.artifacts import MAX_ARTIFACT_BYTES, read_artifact
from carryon.sessions.file_references import project
from carryon.sessions.timeline import project_item


def history_item(path):
    prompt = project('', [{'name': path.name, 'path': str(path)}]).strip()
    return project_item({'id': 'uploaded', 'type': 'userMessage',
                         'content': [{'type': 'text', 'text': prompt}]}, {'turnId': 't'}, 0)


class UploadHistoryTests(unittest.TestCase):
    def test_directory_is_static_and_lstat_does_not_follow_directory_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp, 'uploaded.png')
            folder.mkdir()
            (folder / 'empty').mkdir()
            item = history_item(folder)
            ref = item['artifacts'][0]
            self.assertEqual(item['displayText'], '')
            self.assertEqual(ref['kind'], 'directory')
            self.assertIs(ref['previewAvailable'], False)
            with self.assertRaises((ValueError, BridgeError)):
                read_artifact({'timeline': [item]}, ref['id'])
            link = Path(temp, 'folder-link')
            link.symlink_to(folder, target_is_directory=True)
            linked = history_item(link)
            linked_ref = linked['artifacts'][0]
            self.assertEqual(linked_ref['kind'], 'file')
            self.assertIs(linked_ref['previewAvailable'], False)
            with self.assertRaises(BridgeError):
                read_artifact({'timeline': [linked]}, linked_ref['id'])

    def test_large_file_is_static_while_small_and_boundary_files_keep_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, 'uploaded.bin')
            with path.open('wb') as handle:
                handle.truncate(MAX_ARTIFACT_BYTES + 1)
            item = history_item(path)
            ref = item['artifacts'][0]
            self.assertEqual(ref['kind'], 'file')
            self.assertIs(ref['previewAvailable'], False)
            with self.assertRaises(ValueError):
                read_artifact({'timeline': [item]}, ref['id'])
            with path.open('r+b') as handle:
                handle.truncate(MAX_ARTIFACT_BYTES)
            self.assertNotIn('previewAvailable', history_item(path)['artifacts'][0])
            path.write_bytes(b'hello')
            small = history_item(path)
            self.assertNotIn('previewAvailable', small['artifacts'][0])
            self.assertEqual(read_artifact({'timeline': [small]}, ref['id'])['base64'], 'aGVsbG8=')
