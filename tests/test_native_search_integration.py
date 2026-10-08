"""Public native search in a private home, without loading tasks or model calls."""
import os
import unittest
import test_native_archives_integration as archive_fixtures
from run_appserver_regression import wait_until
from carryon.routes.api import dispatch
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeSearchIntegration(unittest.TestCase):
    setUp = archive_fixtures.NativeArchivesIntegration.setUp
    tearDown = archive_fixtures.NativeArchivesIntegration.tearDown

    def test_search_and_occurrences_do_not_load_or_execute(self):
        self.bridge.disable(); self.bridge.enable(); self.runtime = self.bridge.ipc
        self.assertEqual(self.runtime.rpc('thread/loaded/list', {})['data'], [])
        found = self.runtime.rpc('thread/search', {'searchTerm': 'local fixture only', 'limit': 1, 'sortKey': 'recency_at'})
        self.assertEqual([row['thread']['id'] for row in found['data']], [self.tid])
        self.assertIn('local fixture only', found['data'][0]['snippet'])
        matches = self.runtime.rpc('thread/searchOccurrences', {'threadId': self.tid, 'searchTerm': 'LOCAL fixture', 'limit': 1})
        self.assertEqual(len(matches['data']), 1)
        hit = matches['data'][0]
        self.assertTrue(hit['itemId']); self.assertTrue(hit['turnId']); self.assertTrue(hit['turnCursor'])
        start, end = hit['snippetMatchRange']['start'], hit['snippetMatchRange']['end']
        encoded = hit['snippet'].encode('utf-16-le')
        self.assertEqual(encoded[start*2:end*2].decode('utf-16-le').lower(), 'local fixture')
        self.assertEqual(self.runtime.rpc('thread/loaded/list', {})['data'], [])
        self.assertEqual(self.requests, self.baseline_requests)

    def test_native_search_cursor_pages_unique_threads(self):
        second = self.runtime.create_thread({'cwd': str(self.root), 'historyMode': 'paginated'}, lambda write: write())['id']
        self.runtime.start_turn(second, {'threadId': second, 'input': [{'type': 'text', 'text': 'local fixture only, second', 'text_elements': []}]})
        wait_until(lambda: self.runtime.current(second)['turns'] and self.runtime.current(second)['turns'][-1]['status'] == 'completed')
        wait_until(lambda: len(self.runtime.rpc('thread/search', {'searchTerm': 'local fixture only', 'limit': 10})['data']) == 2)
        baseline = list(self.requests)
        first = self.runtime.rpc('thread/search', {'searchTerm': 'local fixture only', 'limit': 1, 'sortKey': 'recency_at'})
        self.assertEqual(len(first['data']), 1)
        self.assertTrue(first['nextCursor'])
        other = self.runtime.rpc('thread/search', {'searchTerm': 'local fixture only', 'limit': 1, 'sortKey': 'recency_at', 'cursor': first['nextCursor']})
        self.assertEqual(len(other['data']), 1)
        self.assertEqual({first['data'][0]['thread']['id'], other['data'][0]['thread']['id']}, {self.tid, second})
        self.assertEqual(self.requests, baseline)

    def test_api_reads_unloaded_messages_and_owner_preserves_suspension(self):
        self.bridge.disable(); self.bridge.enable(); self.runtime = self.bridge.ipc
        _, found = dispatch(self.bridge, 'GET', '/api/search?search=local%20fixture%20only&limit=1')
        self.assertEqual([row['id'] for row in found['threads']], [self.tid])
        _, hits = dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/search?search=fixture')
        self.assertTrue(hits['occurrences']); self.assertEqual(hits['threadId'], self.tid)
        self.assertEqual(self.runtime.rpc('thread/loaded/list', {})['data'], [])
        manager = archive_fixtures.NativeArchivesIntegration.owner_fixture(self, True)
        before = manager.entries[self.tid]['snapshot']
        _, found = dispatch(self.bridge, 'GET', '/api/search?search=local%20fixture%20only')
        self.assertEqual(found['threads'][0]['id'], self.tid)
        _, hits = dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/search?search=fixture')
        self.assertTrue(hits['occurrences'])
        self.assertIs(manager.entries[self.tid]['snapshot'], before)
        self.assertTrue(manager.entries[self.tid]['suspended'])
        self.assertFalse(self.runtime.connected)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_read_generation_and_revoked_permission_never_publish_results(self):
        from carryon.errors import BridgeError
        original = self.runtime.rpc
        def changed(method, params, *args, **kwargs):
            result = original(method, params, *args, **kwargs)
            if method == 'thread/search': self.bridge.generation += 1
            return result
        with patch.object(self.runtime, 'rpc', changed):
            with self.assertRaises(BridgeError): dispatch(self.bridge, 'GET', '/api/search?search=fixture')
        checks = []
        def authorize():
            checks.append(True)
            if len(checks) == 2: raise PermissionError('revoked')
        with self.assertRaisesRegex(PermissionError, 'revoked'):
            dispatch(self.bridge, 'GET', '/api/search?search=fixture', authorize=authorize)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_occurrences_refuse_archived_and_archive_during_read(self):
        from carryon.desktop_ipc.ipc import IPCError
        from carryon.app_server.app_server import AppServer
        original = self.runtime.rpc
        def archived(method, params, *args, **kwargs):
            result = original(method, params, *args, **kwargs)
            if method == 'thread/searchOccurrences': original('thread/archive', {'threadId': self.tid})
            return result
        with patch.object(self.runtime, 'rpc', archived):
            with self.assertRaisesRegex(IPCError, '已归档'): dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/search?search=fixture')
        with patch.object(AppServer, 'rpc') as native:
            with self.assertRaisesRegex(IPCError, '已归档'): dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/search?search=fixture')
            native.assert_not_called()
        self.assertEqual(self.requests, self.baseline_requests)

    def test_global_missing_inventory_row_keeps_native_cursor(self):
        original = self.bridge.catalog.archive_record
        def missing(tid):
            if tid == self.tid: raise ValueError('会话不存在')
            return original(tid)
        native = self.runtime.rpc('thread/search', {'searchTerm': 'fixture', 'limit': 1, 'sortKey': 'recency_at'})
        with patch.object(self.bridge.catalog, 'archive_record', missing):
            _, result = dispatch(self.bridge, 'GET', '/api/search?search=fixture&limit=1')
            self.assertEqual(result['threads'], [])
            self.assertEqual(result['nextCursor'], native.get('nextCursor'))
        self.assertEqual(self.requests, self.baseline_requests)

    def test_inclusive_occurrence_cursor_locates_native_tail_without_loading(self):
        from urllib.parse import urlencode
        from carryon.desktop_ipc.ipc import IPCError
        self.bridge.disable(); self.bridge.enable(); self.runtime = self.bridge.ipc
        hits = self.runtime.rpc('thread/searchOccurrences', {'threadId': self.tid, 'searchTerm': 'local fixture', 'limit': 1})['data']
        hit = hits[0]; target = '/api/threads/' + self.tid + '/search-anchor?'
        params = {key: hit[key] for key in ('turnCursor', 'turnId', 'itemId')}
        _, anchor = dispatch(self.bridge, 'GET', target + urlencode(params))
        self.assertEqual(anchor, {'threadId': self.tid, 'turnId': hit['turnId'], 'itemId': hit['itemId'], 'historyLimit': 1})
        _, history = dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/history?limit=' + str(anchor['historyLimit']))
        self.assertTrue(any(hit['itemId'] in (row.get('id'), row.get('nativeId')) for row in history['timeline']), history['timeline'])
        with self.assertRaisesRegex(IPCError, '不匹配'):
            dispatch(self.bridge, 'GET', target + urlencode({**params, 'itemId': 'wrong'}))
        self.assertEqual(self.runtime.rpc('thread/loaded/list', {})['data'], [])
        self.assertEqual(self.requests, self.baseline_requests)

    def test_canonical_history_cache_invalidates_on_file_change_and_generation(self):
        self.bridge.disable(); self.bridge.enable(); self.runtime = self.bridge.ipc
        original = self.runtime.rpc
        with patch.object(self.runtime, 'rpc', wraps=original) as native:
            first = self.bridge.persisted_history(self.tid, 1)
            self.assertTrue(any(row['type'] == 'userMessage' for row in first['timeline']))
            self.assertEqual(first['source'], 'native-persisted')
            self.assertFalse(first['access']['nativeReady'])
            calls = sum(call.args[0] == 'thread/turns/list' for call in native.call_args_list)
            cached = self.bridge.persisted_history(self.tid, 1)
            self.assertEqual(cached['historyRevision'], first['historyRevision'])
            self.assertEqual(sum(call.args[0] == 'thread/turns/list' for call in native.call_args_list), calls)
            path = self.bridge.catalog.get(self.tid)['rollout_path']
            os.utime(path, None)
            refreshed = self.bridge.persisted_history(self.tid, 1)
            self.assertGreater(sum(call.args[0] == 'thread/turns/list' for call in native.call_args_list), calls)
            self.assertNotEqual(refreshed['historyRevision'], first['historyRevision'])
            calls = sum(call.args[0] == 'thread/turns/list' for call in native.call_args_list)
            self.bridge.generation += 1
            self.bridge.persisted_history(self.tid, 1)
            self.assertGreater(sum(call.args[0] == 'thread/turns/list' for call in native.call_args_list), calls)
        self.assertEqual(self.runtime.rpc('thread/loaded/list', {})['data'], [])
        self.assertEqual(self.requests, self.baseline_requests)

    def test_owner_canonical_history_preserves_suspended_task_and_closes_reader(self):
        manager = archive_fixtures.NativeArchivesIntegration.owner_fixture(self, True)
        before = manager.entries[self.tid]['snapshot']
        history = self.bridge.persisted_history(self.tid, 1)
        self.assertTrue(any(row['type'] == 'userMessage' for row in history['timeline']))
        self.assertIs(manager.entries[self.tid]['snapshot'], before)
        self.assertTrue(manager.entries[self.tid]['suspended'])
        self.assertFalse(self.runtime.connected)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_cached_history_refuses_archive_and_connection_change_during_lookup(self):
        from carryon.desktop_ipc.ipc import IPCError
        self.bridge.disable(); self.bridge.enable(); self.runtime = self.bridge.ipc
        self.bridge.persisted_history(self.tid, 1)
        # Exercise the cache directly after its caller has obtained a catalog row.
        row = self.bridge.catalog.get(self.tid)
        original = self.bridge.catalog.archive_record
        with patch.object(self.bridge.catalog, 'archive_record', return_value={**original(self.tid), 'archived': True}):
            with self.assertRaisesRegex(IPCError, '已归档'):
                self.bridge.native_history.read(self.bridge, row, 1)
        def changed(tid):
            value = original(tid)
            self.runtime.session_id = 'changed-connection'
            return value
        with patch.object(self.bridge.catalog, 'archive_record', changed):
            with self.assertRaisesRegex(IPCError, '连接已改变'):
                self.bridge.native_history.read(self.bridge, row, 1)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_anchor_counts_opaque_tail_pages_and_rejects_cursor_loops(self):
        from urllib.parse import urlencode
        from carryon.desktop_ipc.ipc import IPCError
        hit = self.runtime.rpc('thread/searchOccurrences', {'threadId': self.tid, 'searchTerm': 'local fixture', 'limit': 1})['data'][0]
        query = urlencode({key: hit[key] for key in ('turnCursor', 'turnId', 'itemId')})
        target = '/api/threads/' + self.tid + '/search-anchor?' + query
        original = self.runtime.rpc
        observed = []
        def pages(method, params, *args, **kwargs):
            if method != 'thread/turns/list': return original(method, params, *args, **kwargs)
            observed.append(dict(params))
            if params['cursor'] == hit['turnCursor']:
                page = original(method, params, *args, **kwargs)
                return {**page, 'nextCursor': 'opaque|tail-one'}
            if params['cursor'] == 'opaque|tail-one':
                return {'data': [{'id': 'tail-' + str(i)} for i in range(100)], 'nextCursor': 'opaque|tail-two'}
            return {'data': [{'id': 'tail-end'}], 'nextCursor': None}
        with patch.object(self.runtime, 'rpc', pages):
            _, result = dispatch(self.bridge, 'GET', target)
        self.assertEqual(result['historyLimit'], 102)
        self.assertEqual([page['cursor'] for page in observed], [hit['turnCursor'], 'opaque|tail-one', 'opaque|tail-two'])
        self.assertEqual([page['itemsView'] for page in observed], ['full', 'summary', 'summary'])
        def loop(method, params, *args, **kwargs):
            result = pages(method, params, *args, **kwargs)
            if method == 'thread/turns/list': result['nextCursor'] = 'opaque|tail-one'
            return result
        with patch.object(self.runtime, 'rpc', loop):
            with self.assertRaisesRegex(IPCError, '游标无效'): dispatch(self.bridge, 'GET', target)
        self.assertEqual(self.requests, self.baseline_requests)
