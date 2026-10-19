"""Public pinned membership in a private home; never real account/sidebar data."""
import os
import unittest
from unittest.mock import patch
import test_native_archives_integration as fixtures
from carryon.app_server.app_server import AppServer
from carryon.errors import IPCError
from carryon.routes.api import dispatch
from carryon.sessions.sections import PINNED_SECTION
from run_appserver_regression import wait_until


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeSectionsIntegration(unittest.TestCase):
    setUp = fixtures.NativeArchivesIntegration.setUp
    tearDown = fixtures.NativeArchivesIntegration.tearDown

    def move(self, key, destination):
        dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/section', {'requestId': key, 'sectionId': destination})
        wait_until(lambda: self.journal.get(key)['state'] not in ('preparing', 'dispatching'))
        return self.journal.get(key)

    def test_public_inventory_pin_and_unpin_stay_unloaded(self):
        self.bridge.disable(); self.bridge.enable(); self.runtime = self.bridge.ipc
        _, inventory = dispatch(self.bridge, 'GET', '/api/sections')
        self.assertTrue(any(row['id'] == PINNED_SECTION and row['pinned'] for row in inventory['sections']))
        self.assertEqual(self.move('pin-once', PINNED_SECTION)['state'], 'completed')
        _, pinned = dispatch(self.bridge, 'GET', '/api/sections/' + PINNED_SECTION + '/threads')
        self.assertEqual([row['id'] for row in pinned['threads']], [self.tid])
        self.assertEqual(self.move('unpin-once', None)['state'], 'completed')
        _, empty = dispatch(self.bridge, 'GET', '/api/sections/' + PINNED_SECTION + '/threads')
        self.assertEqual(empty['threads'], [])
        self.assertEqual(self.runtime.rpc('thread/loaded/list', {})['data'], [])
        self.assertEqual(self.requests, self.baseline_requests)

    def test_unknown_move_queries_without_replaying(self):
        original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/section/move':
                writes.append(dict(params)); raise IPCError('fixture lost reply', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost):
            self.assertEqual(self.move('unknown-pin', PINNED_SECTION)['state'], 'uncertain')
            self.assertEqual(self.move('unknown-pin', PINNED_SECTION)['state'], 'uncertain')
            self.assertEqual(len(writes), 1)
            self.assertEqual(self.bridge.refresh_job('unknown-pin')['state'], 'completed')
        self.assertEqual(self.requests, self.baseline_requests)

    def test_owner_pin_preserves_suspension_and_closes_control(self):
        manager = fixtures.NativeArchivesIntegration.owner_fixture(self, True)
        before = manager.entries[self.tid]['snapshot']
        self.assertEqual(self.move('owner-pin', PINNED_SECTION)['state'], 'completed')
        self.assertIs(manager.entries[self.tid]['snapshot'], before)
        self.assertTrue(manager.entries[self.tid]['suspended'])
        self.assertFalse(self.runtime.connected)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_missing_section_and_revoked_write_do_not_move(self):
        self.assertEqual(self.move('missing-section', '11111111-1111-4111-8111-111111111111')['state'], 'failed')
        def denied(): raise PermissionError('revoked')
        with patch.object(AppServer, 'rpc', wraps=AppServer.rpc) as native:
            with self.assertRaisesRegex(PermissionError, 'revoked'):
                dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/section', {'requestId': 'denied-pin', 'sectionId': PINNED_SECTION}, authorize=denied)
            native.assert_not_called()
        self.assertIsNone(self.journal.get('denied-pin'))
        self.assertEqual(self.requests, self.baseline_requests)

    def test_loaded_owner_writer_is_preserved(self):
        manager = fixtures.NativeArchivesIntegration.owner_fixture(self, False)
        runtime = manager.entries[self.tid]['runtime']
        self.assertEqual(self.move('loaded-owner-pin', PINNED_SECTION)['state'], 'completed')
        self.assertIs(manager.entries[self.tid]['runtime'], runtime)
        self.assertTrue(runtime.connected)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_missing_inventory_row_keeps_cursor_and_unknown_move_blocks_archive(self):
        self.assertEqual(self.move('inventory-pin', PINNED_SECTION)['state'], 'completed')
        native = self.runtime.rpc('thread/list', {'sectionId': PINNED_SECTION, 'sortKey': 'section_position', 'archived': False, 'limit': 1})
        with patch.object(self.bridge.catalog, 'archive_record', side_effect=ValueError('missing')):
            _, page = dispatch(self.bridge, 'GET', '/api/sections/' + PINNED_SECTION + '/threads?limit=1')
        self.assertEqual(page['threads'], [])
        self.assertEqual(page['nextCursor'], native.get('nextCursor'))
        original = AppServer.rpc
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/section/move': raise IPCError('lost', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost): self.assertEqual(self.move('unknown-unpin', None)['state'], 'uncertain')
        with self.assertRaisesRegex(IPCError, '待核对'):
            dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/archive', {'requestId': 'archive-blocked'})
        self.assertIsNone(self.journal.get('archive-blocked'))
        self.assertEqual(self.requests, self.baseline_requests)
