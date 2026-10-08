"""Rename permission, binding identity and native eligibility at real route boundaries."""
import unittest
from unittest.mock import patch
from carryon.routes.remote_scope import scoped_dispatch, request_key
from carryon.sessions.renaming import submit
from carryon.workspaces.workspace_access import required_capabilities
from test_archive_access import ArchiveAccessTests as Fixture

T = '11111111-1111-4111-8111-111111111111'
class RenameAccessTests(unittest.TestCase):
    setUp = Fixture.setUp

    def test_rename_requires_edit_not_send(self):
        self.assertEqual(required_capabilities('POST', '/api/threads/' + T + '/rename', {'name': '名称'}), ('edit',))
        self.assertEqual(required_capabilities('GET', '/api/jobs/name'), ('view',))

    def test_bindings_namespace_names_and_receipts(self):
        with patch('carryon.sessions.renaming.dispatch'):
            _, job = scoped_dispatch(self.bridge, 'POST', '/api/threads/' + T + '/rename', {'requestId': 'same-request', 'name': '名称'}, True, 'one')
            self.assertEqual(job['id'], 'same-request')
        stored = self.bridge.journal.get(request_key('one', 'same-request'))
        self.assertEqual(stored['name'], '名称'); self.assertEqual(stored['sourceBinding'], 'one')
        with self.assertRaises(Exception): scoped_dispatch(self.bridge, 'GET', '/api/jobs/same-request', None, False, 'two')
        with self.assertRaises(Exception): scoped_dispatch(self.bridge, 'POST', '/api/threads/' + T + '/rename', {'requestId': 'reader', 'name': '名称'}, False, 'one')

    def test_invalid_name_or_desktop_follower_creates_no_receipt(self):
        for name in ('', '\n', 'a\nb', 'x' * 201, None):
            with self.assertRaises(ValueError): submit(self.bridge, T, {'requestId': 'invalid', 'name': name})
        self.runtime.protocol = 'desktop-ipc'
        with self.assertRaisesRegex(Exception, 'follower'): submit(self.bridge, T, {'requestId': 'unsupported', 'name': '名称'})
        self.assertEqual(self.bridge.journal.list(), [])

    def test_unknown_metadata_operation_blocks_another_rename(self):
        with patch('carryon.sessions.renaming.dispatch'):
            submit(self.bridge, T, {'requestId': 'original', 'name': '名称'})
        with self.assertRaisesRegex(Exception, '待核对'): submit(self.bridge, T, {'requestId': 'different', 'name': '其他'})
        self.assertIsNone(self.bridge.journal.get('different'))
