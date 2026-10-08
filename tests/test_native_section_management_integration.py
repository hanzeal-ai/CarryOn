"""Native custom-group lifecycle in a private home; no model calls or real data."""
import os
import unittest
from unittest.mock import patch
import test_native_archives_integration as fixtures
from carryon.app_server.app_server import AppServer
from carryon.desktop_ipc.ipc import IPCError
from carryon.routes.api import dispatch
from carryon.routes.remote_scope import scoped_dispatch
from carryon.workspaces.workspace_access import required_capabilities
from run_appserver_regression import wait_until


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeSectionManagementIntegration(unittest.TestCase):
    setUp = fixtures.NativeArchivesIntegration.setUp
    tearDown = fixtures.NativeArchivesIntegration.tearDown

    def send(self, path, body):
        _, receipt = dispatch(self.bridge, 'POST', path, body)
        wait_until(lambda: self.journal.get(receipt['id'])['state'] not in ('preparing', 'dispatching'))
        return self.journal.get(receipt['id'])

    def test_lifecycle_preserves_appearance_and_thread_when_deleted(self):
        created = self.send('/api/sections', {'requestId': 'create-group', 'name': '研发'})
        self.assertEqual(created['state'], 'completed'); sid = created['result']['section']['id']
        self.runtime.rpc('threadSection/update', {'sectionId': sid, 'name': '研发', 'appearance': {'icon': 'folder', 'color': 'blue'}})
        self.runtime.rpc('thread/section/move', {'threadId': self.tid, 'sectionId': sid})
        updated = self.send('/api/sections/' + sid, {'requestId': 'update-group', 'action': 'update', 'name': '已修改'})
        self.assertEqual(updated['state'], 'completed')
        self.assertEqual(updated['result']['section']['appearance'], {'icon': 'folder', 'color': 'blue'})
        removed = self.send('/api/sections/' + sid, {'requestId': 'delete-group', 'action': 'delete'})
        self.assertEqual(removed['state'], 'completed'); self.assertTrue(removed['result']['deleted'])
        self.assertIsNone(self.runtime.rpc('thread/read', {'threadId': self.tid, 'includeTurns': False})['thread']['section'])
        self.assertEqual(self.requests, self.baseline_requests)

    def test_lost_create_cannot_be_guessed_by_matching_name_or_replayed(self):
        original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'threadSection/create': writes.append(params); raise IPCError('lost', uncertain=True)
            return result
        body = {'requestId': 'lost-create-group', 'name': '同名'}
        with patch.object(AppServer, 'rpc', lost):
            receipt = self.send('/api/sections', body)
            self.assertEqual(receipt['state'], 'uncertain')
            self.assertEqual(self.send('/api/sections', body)['state'], 'uncertain')
        self.assertEqual(self.bridge.refresh_job(receipt['id'])['state'], 'uncertain')
        with self.assertRaisesRegex(IPCError, '待核对'): self.send('/api/sections', {'requestId': 'second-create', 'name': '同名'})
        self.assertEqual(len(writes), 1); self.assertEqual(self.requests, self.baseline_requests)

    def test_lost_update_and_delete_recover_from_canonical_inventory_without_replay(self):
        sid = self.send('/api/sections', {'requestId': 'create-recovery', 'name': '恢复'})['result']['section']['id']
        original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method in ('threadSection/update', 'threadSection/delete'): writes.append(method); raise IPCError('lost', uncertain=True)
            return result
        with patch.object(AppServer, 'rpc', lost):
            self.assertEqual(self.send('/api/sections/' + sid, {'requestId': 'unknown-update', 'action': 'update', 'name': '恢复完成'})['state'], 'uncertain')
            self.assertEqual(self.bridge.refresh_job('unknown-update')['state'], 'completed')
            self.assertEqual(self.send('/api/sections/' + sid, {'requestId': 'unknown-delete', 'action': 'delete'})['state'], 'uncertain')
            self.assertEqual(self.bridge.refresh_job('unknown-delete')['state'], 'completed')
        self.assertEqual(writes, ['threadSection/update', 'threadSection/delete'])
        self.assertEqual(self.requests, self.baseline_requests)

    def test_remote_receipts_namespaced_and_edit_only(self):
        body = {'requestId': 'remote-create', 'name': '远程'}
        _, job = scoped_dispatch(self.bridge, 'POST', '/api/sections', body, True, 'binding-one')
        self.assertEqual(job['id'], body['requestId'])
        self.assertEqual(required_capabilities('POST', '/api/sections', body), ('edit',))
        wait_until(lambda: self.journal.list()[0]['state'] not in ('preparing', 'dispatching'))
        _, receipt = scoped_dispatch(self.bridge, 'GET', '/api/jobs/remote-create', None, True, 'binding-one')
        self.assertEqual(receipt['state'], 'completed')
        with self.assertRaises(Exception): scoped_dispatch(self.bridge, 'GET', '/api/jobs/remote-create', None, True, 'binding-two')
        with self.assertRaises(Exception): scoped_dispatch(self.bridge, 'POST', '/api/sections', body, False, 'binding-one')

    def test_lifecycle_and_moves_interlock_in_both_orders(self):
        sid = self.send('/api/sections', {'requestId': 'interlock-create', 'name': '互锁'})['result']['section']['id']
        for kind, destination in [('section-delete', sid), ('section-create', None), ('section-update', sid)]:
            key = 'pending-' + kind
            self.journal.insert({'id': key, 'kind': kind, 'threadId': destination or 'sections', 'sectionId': destination, 'fingerprint': key, 'state': 'uncertain', 'created': 0})
            with self.assertRaisesRegex(IPCError, '待核对'):
                dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/section', {'requestId': 'blocked-' + kind, 'sectionId': sid})
            self.assertIsNone(self.journal.get('blocked-' + kind))
            self.journal.update(key, state='failed')
        self.journal.insert({'id': 'moving-out', 'kind': 'section-move', 'threadId': self.tid, 'sectionId': None, 'fingerprint': 'moving', 'state': 'uncertain', 'created': 0})
        with self.assertRaisesRegex(IPCError, '待核对'):
            self.send('/api/sections/' + sid, {'requestId': 'delete-while-moving', 'action': 'delete'})
        self.assertIsNone(self.journal.get('delete-while-moving'))
        self.assertEqual(self.requests, self.baseline_requests)

    def test_native_order_matches_adjacent_target_and_append_without_loading(self):
        sid = self.send('/api/sections', {'requestId': 'ordering-group', 'name': '排序'})['result']['section']['id']
        ids = [self.tid] + [self.runtime.create_thread({'cwd': str(self.root), 'historyMode': 'paginated'}, lambda write: write())['id'] for _ in range(2)]
        for tid in ids: self.runtime.rpc('thread/section/move', {'threadId': tid, 'sectionId': sid})
        self.bridge.disable(); self.bridge.enable(); self.runtime = self.bridge.ipc
        body = {'requestId': 'order-before', 'action': 'order', 'threadId': ids[2], 'beforeThreadId': ids[0]}
        self.assertEqual(self.send('/api/sections/' + sid, body)['state'], 'completed')
        _, page = dispatch(self.bridge, 'GET', '/api/sections/' + sid + '/threads')
        self.assertEqual([row['id'] for row in page['threads']], [ids[2], ids[0], ids[1]])
        self.assertEqual(self.send('/api/sections/' + sid, {**body, 'requestId': 'order-append', 'beforeThreadId': None})['state'], 'completed')
        _, page = dispatch(self.bridge, 'GET', '/api/sections/' + sid + '/threads')
        self.assertEqual([row['id'] for row in page['threads']], ids)
        self.assertEqual(self.runtime.rpc('thread/loaded/list', {})['data'], [])
        self.assertEqual(self.requests, self.baseline_requests)

    def test_unknown_order_requires_exact_native_position_and_does_not_replay(self):
        sid = self.send('/api/sections', {'requestId': 'unknown-order-group', 'name': '排序'})['result']['section']['id']
        other = self.runtime.create_thread({'cwd': str(self.root), 'historyMode': 'paginated'}, lambda write: write())['id']
        for tid in [self.tid, other]: self.runtime.rpc('thread/section/move', {'threadId': tid, 'sectionId': sid})
        original = AppServer.rpc; writes = []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/section/move': writes.append(params); raise IPCError('lost order reply', uncertain=True)
            return result
        body = {'requestId': 'unknown-order', 'action': 'order', 'threadId': other, 'beforeThreadId': self.tid}
        with patch.object(AppServer, 'rpc', lost): self.assertEqual(self.send('/api/sections/' + sid, body)['state'], 'uncertain')
        self.runtime.rpc('thread/section/move', {'threadId': other, 'sectionId': sid})
        self.assertEqual(self.bridge.refresh_job(body['requestId'])['state'], 'uncertain')
        self.runtime.rpc('thread/section/move', {'threadId': other, 'sectionId': sid, 'beforeThreadId': self.tid})
        self.assertEqual(self.bridge.refresh_job(body['requestId'])['state'], 'completed')
        self.assertEqual(len(writes), 1); self.assertEqual(self.requests, self.baseline_requests)

    def test_order_rejects_foreign_anchor_and_blocks_archive_in_both_orders(self):
        sid = self.send('/api/sections', {'requestId': 'rejected-order-group', 'name': '排序'})['result']['section']['id']
        self.runtime.rpc('thread/section/move', {'threadId': self.tid, 'sectionId': sid})
        other = self.runtime.create_thread({'cwd': str(self.root), 'historyMode': 'paginated'}, lambda write: write())['id']
        from carryon.sessions.sections import PINNED_SECTION
        self.runtime.rpc('thread/section/move', {'threadId': other, 'sectionId': PINNED_SECTION})
        body = {'requestId': 'foreign-order', 'action': 'order', 'threadId': self.tid, 'beforeThreadId': other}
        self.assertEqual(self.send('/api/sections/' + sid, body)['state'], 'failed')
        for kind in ['archive', 'section-order']:
            self.journal.insert({'id': 'pending-' + kind, 'kind': kind, 'threadId': self.tid, 'sectionId': sid, 'fingerprint': kind, 'state': 'uncertain', 'created': 0})
            with self.assertRaisesRegex(IPCError, '待核对'):
                if kind == 'archive': self.send('/api/sections/' + sid, {**body, 'requestId': 'blocked-order', 'beforeThreadId': None})
                else: dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/archive', {'requestId': 'blocked-archive'})
            self.journal.update('pending-' + kind, state='failed')
        self.assertEqual(self.requests, self.baseline_requests)

    def test_order_anchor_archive_interlock_in_both_orders_and_before_dispatch(self):
        sid = self.send('/api/sections', {'requestId': 'anchor-order-group', 'name': '锚点排序'})['result']['section']['id']
        anchor = self.runtime.create_thread({'cwd': str(self.root), 'historyMode': 'paginated'}, lambda write: write())['id']
        for tid in [self.tid, anchor]: self.runtime.rpc('thread/section/move', {'threadId': tid, 'sectionId': sid})
        self.journal.insert({'id': 'anchor-archive-pending', 'kind': 'archive', 'threadId': anchor, 'fingerprint': 'anchor', 'state': 'uncertain', 'created': 0})
        body = {'requestId': 'anchor-order-blocked', 'action': 'order', 'threadId': self.tid, 'beforeThreadId': anchor}
        with self.assertRaisesRegex(IPCError, '待核对'): self.send('/api/sections/' + sid, body)
        self.assertIsNone(self.journal.get(body['requestId']))
        self.journal.update('anchor-archive-pending', state='failed')
        self.journal.insert({'id': 'anchor-order-pending', 'kind': 'section-order', 'threadId': self.tid, 'sectionId': sid, 'body': {'action': 'order', 'threadId': self.tid, 'beforeThreadId': anchor}, 'fingerprint': 'anchor-order', 'state': 'uncertain', 'created': 0})
        with self.assertRaisesRegex(IPCError, '待核对'):
            dispatch(self.bridge, 'POST', '/api/threads/' + anchor + '/archive', {'requestId': 'anchor-archive-blocked'})
        self.assertIsNone(self.journal.get('anchor-archive-blocked'))
        self.journal.update('anchor-order-pending', state='failed')
        original = AppServer.rpc; sent = []
        def changed(runtime, method, params, *args, **kwargs):
            if method == 'thread/section/move':
                original(runtime, 'thread/archive', {'threadId': anchor})
                sent.append(method)
            return original(runtime, method, params, *args, **kwargs)
        wire, native_write = [], self.runtime._write
        def observed(payload):
            wire.append(payload.get('method')); native_write(payload)
        with patch.object(AppServer, 'rpc', changed), patch.object(self.runtime, '_write', observed):
            self.assertEqual(self.send('/api/sections/' + sid, {**body, 'requestId': 'anchor-order-recheck'})['state'], 'failed')
        self.assertEqual(sent, ['thread/section/move'])
        self.assertNotIn('thread/section/move', wire)
        self.assertEqual(self.requests, self.baseline_requests)
