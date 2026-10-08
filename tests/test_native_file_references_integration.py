"""Native file search in a private home; no real account or file upload."""
import os
import unittest
from pathlib import Path
import test_native_archives_integration as fixture
from carryon.routes.api import dispatch
from carryon.sessions.file_references import guard, project
from carryon.sessions.user_messages import unwrap_user_message


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit private native fixture required')
class NativeFileReferencesIntegration(unittest.TestCase):
    setUp = fixture.NativeArchivesIntegration.setUp
    def tearDown(self):
        if hasattr(self.bridge, "shutdown"):
            self.bridge.shutdown()
        fixture.NativeArchivesIntegration.tearDown(self)

    def search(self):
        source = self.root / 'unique-project-source.swift'
        source.write_text('struct PrivateFixture {}\n')
        _, result = dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/files/search?query=unique-project-source')
        self.assertEqual(result['cwd'], str(Path(self.runtime.current(self.tid)['cwd']).resolve()))
        self.assertEqual(result['cwd'], str(self.root.resolve()))
        self.assertEqual(result['files'], [{'name': source.name, 'path': str(source.resolve()), 'relativePath': source.name, 'query': 'unique-project-source'}])
        return source, result['files'][0]

    def test_search_and_final_guard_use_exact_native_root_without_model_call(self):
        source, row = self.search()
        files = [{key: row[key] for key in ('name', 'path', 'query')}]
        writes = []
        guard(self.runtime, self.tid, files, None)(lambda: writes.append(project('检查这个文件', files)))
        self.assertEqual(unwrap_user_message(writes[0]), ('检查这个文件', [str(source.resolve())]))
        self.assertEqual(self.requests, self.baseline_requests)

    def test_suspended_owner_read_does_not_resume_or_change_snapshot(self):
        source = self.root / 'unique-project-source.swift'; source.write_text('local')
        manager = fixture.NativeArchivesIntegration.owner_fixture(self, True)
        original = manager.entries[self.tid]['runtime']; snapshot = manager.entries[self.tid]['snapshot']
        _, page = dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/files/search?query=unique-project-source')
        self.assertEqual(page['files'][0]['path'], str(source.resolve()))
        self.assertIs(manager.entries[self.tid]['runtime'], original)
        self.assertIs(manager.entries[self.tid]['snapshot'], snapshot)
        self.assertTrue(manager.entries[self.tid]['suspended']); self.assertFalse(original.connected)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_permission_revocation_after_search_does_not_return_paths(self):
        from carryon.errors import BridgeError
        allowed = [True]
        original = self.runtime.rpc
        def revoked(method, params, *args, **kwargs):
            result = original(method, params, *args, **kwargs)
            if method == 'fuzzyFileSearch': allowed[0] = False
            return result
        def authorize():
            if not allowed[0]: raise BridgeError('fixture revoked', 403)
        from unittest.mock import patch
        with patch.object(self.runtime, 'rpc', revoked):
            with self.assertRaises(BridgeError):
                dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/files/search?query=source', authorize=authorize)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_compose_native_text_and_original_request_identity(self):
        source, row = self.search()
        files = [{key: row[key] for key in ('name', 'path', 'query')}]
        body = {'requestId': 'file-compose-original', 'prompt': '检查项目文件', 'files': files}
        _, job = dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/compose', body)
        self.assertEqual(job['state'], 'accepted', job)
        self.assertEqual(job['files'], files)
        fixture.wait_until(lambda: self.runtime.current(self.tid)['turns'][-1]['status'] == 'completed')
        native = self.runtime.rpc('thread/read', {'threadId': self.tid, 'includeTurns': True})['thread']['turns'][-1]
        user = next(item for item in native['items'] if item['type'] == 'userMessage')
        self.assertEqual(user['content'], [{'type': 'text', 'text': project('检查项目文件', files), 'text_elements': []}])
        self.assertEqual(unwrap_user_message(user['content'][0]['text']), ('检查项目文件', [str(source.resolve())]))
        count = len(self.requests)
        _, repeated = dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/compose', body)
        self.assertEqual(repeated['id'], job['id']); self.assertEqual(len(self.requests), count)
        from carryon.errors import BridgeError
        with self.assertRaises(BridgeError):
            dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/compose', {**body, 'files': [{**files[0], 'query': 'changed'}]})

    def test_file_removed_after_discovery_never_starts_turn(self):
        source, row = self.search(); source.unlink()
        files = [{key: row[key] for key in ('name', 'path', 'query')}]
        _, job = dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/compose', {'requestId': 'deleted-file-reference', 'prompt': '检查', 'files': files})
        self.assertEqual(job['state'], 'failed', job)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_loaded_owner_compose_uses_file_context(self):
        fixture.NativeArchivesIntegration.owner_fixture(self, False)
        source, row = self.search()
        files = [{key: row[key] for key in ('name', 'path', 'query')}]
        _, job = dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/compose', {'requestId': 'owner-file-reference', 'prompt': '检查项目文件', 'files': files})
        fixture.wait_until(lambda: self.journal.get(job['id'])['state'] not in ('preparing', 'dispatching'))
        job = self.journal.get(job['id'])
        self.assertEqual(job['state'], 'accepted', job)
        fixture.wait_until(lambda: self.runtime.current(self.tid)['turns'][-1]['status'] == 'completed')
        turn = self.runtime.rpc('thread/read', {'threadId': self.tid, 'includeTurns': True})['thread']['turns'][-1]
        user = next(item for item in turn['items'] if item['type'] == 'userMessage')
        self.assertEqual(unwrap_user_message(user['content'][0]['text']), ('检查项目文件', [str(source.resolve())]))

    def test_owner_checks_deleted_file_at_native_write_boundary(self):
        from unittest.mock import patch
        fixture.NativeArchivesIntegration.owner_fixture(self, False)
        source, row = self.search()
        files = [{key: row[key] for key in ('name', 'path', 'query')}]
        original = self.runtime.rpc
        def delayed(method, params, *args, **kwargs):
            if method == 'turn/start':
                source.unlink()
            return original(method, params, *args, **kwargs)
        with patch.object(self.runtime, 'rpc', side_effect=delayed):
            _, job = dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/compose', {'requestId': 'owner-deleted-file-boundary', 'prompt': '检查', 'files': files})
            fixture.wait_until(lambda: self.journal.get(job['id'])['state'] not in ('preparing', 'dispatching'))
        self.assertEqual(self.journal.get(job['id'])['state'], 'failed', self.journal.get(job['id']))
        self.assertEqual(self.requests, self.baseline_requests)

    def test_owner_final_authorization_rejects_without_wire_or_future_marker(self):
        from unittest.mock import patch
        from carryon.errors import BridgeError
        manager = fixture.NativeArchivesIntegration.owner_fixture(self, False)
        source, row = self.search()
        files = [{key: row[key] for key in ('name', 'path', 'query')}]
        original = self.runtime.rpc
        entering_native_write = False
        def delayed(method, params, *args, **kwargs):
            nonlocal entering_native_write
            if method == 'turn/start': entering_native_write = True
            return original(method, params, *args, **kwargs)
        def authorize():
            if entering_native_write: raise BridgeError('fixture permission revoked', 403)
        with patch.object(self.runtime, 'rpc', side_effect=delayed):
            _, job = dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/compose', {'requestId': 'owner-revoked-file-boundary', 'prompt': '检查', 'files': files}, authorize=authorize)
            fixture.wait_until(lambda: self.journal.get(job['id'])['state'] not in ('preparing', 'dispatching'))
        self.assertEqual(self.journal.get(job['id'])['state'], 'failed', self.journal.get(job['id']))
        self.assertEqual(self.requests, self.baseline_requests)
        with manager.lock: self.assertFalse(manager.entries[self.tid]['awaiting_new_turn'])

    def test_loaded_owner_queue_keeps_file_context_and_tracks_future_turn(self):
        manager = fixture.NativeArchivesIntegration.owner_fixture(self, False)
        self.test_queue_keeps_ordinary_text_context_and_never_uses_file_mention()
        with manager.lock:
            entry = manager.entries.get(self.tid)
            self.assertTrue(entry is None or entry['awaiting_new_turn'] or entry['submitted_turn_ids'])

    def test_queue_keeps_ordinary_text_context_and_never_uses_file_mention(self):
        import threading
        from unittest.mock import patch
        source, row = self.search()
        files = [{key: row[key] for key in ('name', 'path', 'query')}]
        gate, entered = threading.Event(), threading.Event()
        original = fixture.Model.do_POST
        def blocked(handler):
            entered.set(); gate.wait(10); original(handler)
        with patch.object(fixture.Model, 'do_POST', blocked):
            try:
                self.runtime.start_turn(self.tid, {'threadId': self.tid, 'input': [{'type': 'text', 'text': 'private blocked fixture', 'text_elements': []}]})
                self.assertTrue(entered.wait(5))
                count = len(self.requests)
                queue = self.bridge.queue(self.tid, authoritative=True)
                _, job = dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/operations', {'requestId': 'queued-file-reference', 'action': 'queue-add', 'prompt': '检查项目文件', 'files': files, 'queueFingerprint': queue['fingerprint']})
                self.assertEqual(job['state'], 'completed', job)
                rows = self.runtime.rpc('thread/queue/list', {'threadId': self.tid})['data']
                self.assertEqual(len(rows), 1)
                self.assertEqual([item['type'] for item in rows[0]['input']], ['text'])
                self.assertEqual(unwrap_user_message(rows[0]['input'][0]['text']), ('检查项目文件', [str(source.resolve())]))
                self.assertEqual(len(self.requests), count)
            finally:
                gate.set()
            fixture.wait_until(lambda: len(self.runtime.current(self.tid)['turns']) >= 3 and self.runtime.current(self.tid)['turns'][-1]['status'] == 'completed')
