"""Archive access and binding identity at production route boundaries."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from carryon.errors import BridgeError
from carryon.routes.api import dispatch
from carryon.routes.remote_scope import scoped_dispatch, request_key
from carryon.sessions.archives import submit
from carryon.sessions.native_metadata import record
from carryon.store import Journal
from carryon.workspaces.workspace_access import required_capabilities, require

T = '11111111-1111-4111-8111-111111111111'

class ArchiveAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        journal = Journal(Path(self.temp.name) / 'jobs.sqlite'); self.addCleanup(journal.conn.close)
        self.runtime = SimpleNamespace(protocol='codex-app-server')
        self.row = {'id': T, 'archived': False, 'history_mode': 'paginated', 'source': 'cli'}
        self.bridge = SimpleNamespace(ipc=self.runtime, journal=journal, lock=threading.RLock(),
            catalog=SimpleNamespace(archive_record=lambda tid: self.row), require=lambda: (self.runtime, 0),
            check_generation=lambda ipc, generation: None, refresh_job=journal.get)

    def test_view_only_reads_inventory_and_jobs_but_cannot_archive_or_restore(self):
        members = {'reader': ['view']}
        server = SimpleNamespace(sessions={'key': time.monotonic() + 60},
            auth=SimpleNamespace(identity=lambda key: 'reader'), config={'devices': {'mac': {'members': members}}})
        for path in ('/api/archived', '/api/jobs/archive-original'):
            require(server, 'key', 'mac', required_capabilities('GET', path))
        for action in ('archive', 'unarchive'):
            needed = required_capabilities('POST', '/api/threads/' + T + '/' + action)
            with self.assertRaises(PermissionError): require(server, 'key', 'mac', needed)
            members['reader'] = ['view', 'edit']; require(server, 'key', 'mac', needed)
            members['reader'] = ['view']

    def test_bindings_keep_original_receipt_identity_without_exposing_other_binding(self):
        path = '/api/threads/' + T + '/archive'
        with patch('carryon.sessions.archives.dispatch') as native:
            for binding in ('one', 'two'):
                code, job = scoped_dispatch(self.bridge, 'POST', path, {'requestId': 'same-original'}, True, binding)
                self.assertEqual(code, 202); self.assertEqual(job['id'], 'same-original')
                self.bridge.journal.update(request_key(binding, 'same-original'), state='failed')
            deadline = time.monotonic() + 1
            while native.call_count < 2 and time.monotonic() < deadline: time.sleep(.01)
            self.assertEqual(native.call_count, 2)
        self.assertNotEqual(request_key('one', 'same-original'), request_key('two', 'same-original'))
        for binding in ('one', 'two'):
            job = scoped_dispatch(self.bridge, 'GET', '/api/jobs/same-original', None, False, binding)[1]
            self.assertEqual(job['id'], 'same-original'); self.assertNotIn('sourceBinding', job)
        with self.assertRaises(BridgeError): scoped_dispatch(self.bridge, 'GET', '/api/jobs/same-original', None, False, 'other')
        with self.assertRaises(BridgeError): scoped_dispatch(self.bridge, 'POST', path, {'requestId': 'reader-write'}, False, 'one')

    def test_desktop_follower_cannot_create_archive_job_or_dispatch_native_write(self):
        self.runtime.protocol = 'desktop-ipc'
        with patch('carryon.sessions.archives.dispatch') as native:
            with self.assertRaisesRegex(Exception, 'follower'): submit(self.bridge, T, 'archive', {'requestId': 'unsupported'})
            native.assert_not_called()
        self.assertEqual(self.bridge.journal.list(), [])

    def test_subagent_record_cannot_be_archived_or_restored(self):
        self.row['thread_source'] = 'subagent'
        with self.assertRaisesRegex(Exception, '子会话'): record(self.bridge, T)

    def test_inventory_is_read_only_and_pagination_uses_returned_count(self):
        calls = []
        self.runtime.protocol = 'desktop-ipc'
        self.bridge.catalog.archived_list = lambda limit, offset, search: calls.append((limit, offset, search)) or [{'id': T}]
        code, page = dispatch(self.bridge, 'GET', '/api/archived?limit=999&offset=4&search=%E5%AE%A1%E6%9F%A5', remote=True)
        self.assertEqual(code, 200); self.assertEqual(calls, [(100, 4, '审查')])
        self.assertFalse(page['supportsRestore']); self.assertEqual(page['nextOffset'], 5)
        self.assertEqual(self.bridge.journal.list(), [])
