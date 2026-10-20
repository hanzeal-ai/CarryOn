"""Upload storage/security tests use temporary directories and no native service."""
import base64
import hashlib
import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from carryon.errors import BridgeError
from carryon.routes.api import dispatch
from carryon.routes.remote_scope import scoped_dispatch
from carryon.sessions.file_references import project
from carryon.sessions.user_messages import HEADER, unwrap_user_message
from carryon.uploads import LIMITS, Uploads, manifest, project_request
from carryon.workspaces.workspace_access import required_capabilities

T = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
TARGET = {'type': 'thread', 'threadId': T}


def file_entry(path, data):
    return {'path': path, 'kind': 'file', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def begin_body(data=b'hello', name='hello.txt', target=None):
    return {'action': 'begin', 'requestId': 'upload-request', 'name': name, 'kind': 'file',
            'entries': [file_entry(name, data)], 'target': target or TARGET}


def chunk_body(identifier, data, offset=0, path='hello.txt'):
    return {'action': 'chunk', 'uploadId': identifier, 'path': path, 'offset': offset,
            'data': base64.b64encode(data).decode()}


class FakeBridge:
    def __init__(self, directory):
        self.workspace_directory = Path(directory)
        self.catalog = SimpleNamespace(independent=True)
        self.enabled = True
        self.sent = []

    def require(self):
        if not self.enabled:
            raise BridgeError('disabled', 403)

    def assert_target(self, tid):
        if tid not in (T, OTHER):
            raise BridgeError('missing', 404)

    def compose(self, tid, request_id, prompt, *_args, **_kwargs):
        self.sent.append((tid, prompt))
        return {'id': request_id, 'state': 'sent'}


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = FakeBridge(self.temp.name)
        self.uploads = Uploads(self.bridge)

    def tearDown(self):
        # Completed batches are sealed; test cleanup remains scoped to its temp.
        for directory, dirs, files in os.walk(self.temp.name):
            os.chmod(directory, 0o700)
            for name in files:
                path = Path(directory, name)
                if not path.is_symlink():
                    os.chmod(path, 0o600)
        self.temp.cleanup()

    def completed(self, data=b'hello', body=None, uploader=None):
        uploader = uploader or self.uploads
        body = body or begin_body(data)
        receipt = uploader.begin(body)
        if data:
            uploader.chunk(chunk_body(receipt['id'], data, path=body['name']))
        return uploader.complete({'uploadId': receipt['id']})

    def test_multiple_chunks_can_replay_from_zero_before_and_after_completion(self):
        data = bytes(range(256)) * 600
        body = begin_body(data)
        receipt = self.uploads.begin(body)
        self.assertEqual(receipt, self.uploads.begin(body))
        chunks = list(range(0, len(data), LIMITS['chunkBytes']))
        for offset in chunks:
            block = data[offset:offset + LIMITS['chunkBytes']]
            self.assertEqual(self.uploads.chunk(chunk_body(receipt['id'], block, offset)), {'offset': offset + len(block)})
        for complete in (False, True):
            if complete:
                receipt = self.uploads.complete({'uploadId': receipt['id']})
                self.assertEqual(receipt['target'], TARGET)
                self.assertEqual(Path(receipt['path']).read_bytes(), data)
                self.assertEqual(stat.S_IMODE(Path(receipt['path']).stat().st_mode), 0o400)
                self.assertEqual(self.uploads.complete({'uploadId': receipt['id']}), receipt)
            for offset in chunks:
                block = data[offset:offset + LIMITS['chunkBytes']]
                self.assertEqual(self.uploads.chunk(chunk_body(receipt['id'], block, offset)), {'offset': offset + len(block)})
        self.assertEqual(self.uploads.read(receipt['id'])['entries'][0]['offset'], len(data))
        with self.assertRaises(BridgeError):
            self.uploads.chunk(chunk_body(receipt['id'], b'bad', 0))

    def test_partial_system_write_replays_existing_prefix_then_appends(self):
        receipt = self.uploads.begin(begin_body())
        path = Path(self.temp.name, 'attachments', receipt['id'], 'content', 'hello.txt')
        path.write_bytes(b'he')
        self.assertEqual(self.uploads.chunk(chunk_body(receipt['id'], b'hello')), {'offset': 5})
        self.assertEqual(self.uploads.complete({'uploadId': receipt['id']})['state'], 'complete')

    def test_empty_directory_and_tree_keep_structure_without_touching_project(self):
        body = {'action': 'begin', 'requestId': 'folder-request', 'name': 'folder', 'kind': 'directory',
                'target': TARGET, 'entries': [{'path': 'folder', 'kind': 'directory'},
                    {'path': 'folder/empty', 'kind': 'directory'}, file_entry('folder/a.txt', b'hello'),
                    file_entry('folder/b.txt', b'world')]}
        receipt = self.uploads.begin(body)
        self.uploads.chunk(chunk_body(receipt['id'], b'hello', path='folder/a.txt'))
        with self.assertRaises(BridgeError):
            self.uploads.complete({'uploadId': receipt['id']})
        path = Path(self.temp.name, 'attachments', receipt['id'], 'content', 'folder/a.txt')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.uploads.chunk(chunk_body(receipt['id'], b'world', path='folder/b.txt'))
        complete = self.uploads.complete({'uploadId': receipt['id']})
        self.assertTrue(Path(complete['path'], 'empty').is_dir())
        self.assertEqual(Path(complete['path'], 'b.txt').read_bytes(), b'world')
        empty = {**body, 'requestId': 'empty-folder', 'entries': body['entries'][:2]}
        self.assertEqual(self.uploads.complete({'uploadId': self.uploads.begin(empty)['id']})['state'], 'complete')
        self.assertEqual(set(Path(self.temp.name).iterdir()), {Path(self.temp.name, 'attachments')})

    def test_begin_conflicts_parallel_retries_and_reserved_quota(self):
        body = begin_body()
        with ThreadPoolExecutor(max_workers=4) as executor:
            receipts = list(executor.map(lambda _: Uploads(self.bridge).begin(body), range(8)))
        self.assertEqual(len({receipt['id'] for receipt in receipts}), 1)
        with self.assertRaises(BridgeError):
            self.uploads.begin(begin_body(b'other'))
        with patch('carryon.uploads.MAX_STORAGE_BYTES', 5000):
            self.assertEqual(self.uploads.begin(body)['id'], receipts[0]['id'])
            with self.assertRaises(BridgeError):
                self.uploads.begin({**body, 'requestId': 'second-upload'})

    def test_manifest_rejects_paths_links_duplicates_limits_and_missing_parents(self):
        invalid_paths = ('../escape', '/absolute', 'a\\b', 'a//b', 'a/./b', 'a/../b',
                         'bad\nname', 'x:y', 'name.', ' name', 'x' * 256)
        for name in invalid_paths:
            with self.subTest(path=name), self.assertRaises(ValueError):
                manifest(begin_body(name=name))
        body = {'name': 'root', 'kind': 'directory', 'entries': [{'path': 'root', 'kind': 'directory'}]}
        for extra in ([file_entry('root/missing/a', b'')],
                      [{'path': 'root/link', 'kind': 'symlink'}],
                      [file_entry('root/a', b''), file_entry('root/A', b'')],
                      [file_entry('root/é', b''), file_entry('root/e\u0301', b'')],
                      [{**file_entry('root/a', b''), 'size': True}],
                      [{**file_entry('root/a', b''), 'size': LIMITS['maxFileBytes'] + 1}],
                      [file_entry('root/a', b'')] * 100):
            with self.subTest(extra=extra[:1]), self.assertRaises(ValueError):
                manifest({**body, 'entries': body['entries'] + extra})
        too_big = [dict(file_entry('root/' + str(i), b''), size=LIMITS['maxFileBytes']) for i in range(3)]
        with self.assertRaises(ValueError):
            manifest({**body, 'entries': body['entries'] + too_big})

    def test_owner_target_revocation_and_corrupted_completed_content_fail_closed(self):
        source = {'sourceBinding': 'binding-a', 'sourceAccount': 'account-a'}
        uploader = Uploads(self.bridge, source)
        receipt = self.completed(uploader=uploader)
        for alien in (None, {**source, 'sourceAccount': 'account-b'}, {**source, 'sourceBinding': 'binding-b'}):
            with self.assertRaises(BridgeError) as failure:
                Uploads(self.bridge, alien).read(receipt['id'])
            self.assertEqual(failure.exception.status, 404)
        data = {'uploads': [receipt['id']], 'prompt': 'review'}
        with self.assertRaises(BridgeError):
            uploader.project(data, {'type': 'thread', 'threadId': OTHER})
        with self.assertRaises(PermissionError):
            Uploads(self.bridge, source, lambda: (_ for _ in ()).throw(PermissionError('revoked'))).read(receipt['id'])
        self.bridge.enabled = False
        with self.assertRaises(BridgeError):
            uploader.read(receipt['id'])
        self.bridge.enabled = True
        path = Path(receipt['path']); path.chmod(0o600); path.write_bytes(b'other')
        with self.assertRaises(BridgeError):
            uploader.project(data, TARGET)

    def test_symlink_hardlink_special_file_and_extra_file_are_rejected(self):
        outside = Path(self.temp.name, 'outside.txt'); outside.write_bytes(b'hello')
        for kind in ('symlink', 'hardlink', 'fifo', 'extra'):
            body = {**begin_body(), 'requestId': 'attack-' + kind}
            receipt = self.uploads.begin(body)
            path = Path(self.temp.name, 'attachments', receipt['id'], 'content', 'hello.txt')
            if kind == 'extra':
                path.write_bytes(b'hello'); path.with_name('unexpected').write_bytes(b'')
            else:
                path.unlink()
                if kind == 'symlink': path.symlink_to(outside)
                elif kind == 'hardlink': os.link(outside, path)
                else: os.mkfifo(path)
            with self.assertRaises(BridgeError):
                self.uploads.complete({'uploadId': receipt['id']})
        self.assertEqual(outside.read_bytes(), b'hello')

    def test_attachment_root_symlink_cannot_select_server_directory(self):
        outside = Path(self.temp.name, 'project'); outside.mkdir()
        Path(self.temp.name, 'attachments').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(BridgeError):
            self.uploads.begin(begin_body())
        self.assertEqual(list(outside.iterdir()), [])

    def test_revocation_and_record_write_failures_do_not_poison_future_begin(self):
        calls = 0
        def revoke():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise BridgeError('revoked', 403)
        with self.assertRaises(BridgeError):
            Uploads(self.bridge, authorize=revoke).begin(begin_body())
        from carryon.uploads import _save_record
        with patch('carryon.uploads._save_record', side_effect=OSError('disk full')):
            with self.assertRaises(BridgeError):
                self.uploads.begin(begin_body())
        self.assertFalse(list(Path(self.temp.name, 'attachments').glob('.pending-*')))
        receipt = self.uploads.begin(begin_body())
        self.uploads.chunk(chunk_body(receipt['id'], b'hello'))
        with patch('carryon.uploads._save_record', side_effect=OSError('disk full')):
            with self.assertRaises(BridgeError):
                self.uploads.complete({'uploadId': receipt['id']})
        self.assertEqual(self.uploads.chunk(chunk_body(receipt['id'], b'hello')), {'offset': 5})
        self.assertEqual(self.uploads.complete({'uploadId': receipt['id']})['state'], 'complete')

    def test_route_projection_preserves_prompt_and_has_one_file_envelope(self):
        receipt = self.completed()
        payload = {'requestId': 'send-request', 'prompt': '检查内容', 'uploads': [receipt['id']]}
        status, _ = dispatch(self.bridge, 'POST', f'/api/threads/{T}/compose', payload)
        self.assertEqual(status, 202)
        prompt = self.bridge.sent[0][1]
        combined = project(prompt, [{'name': 'source.py', 'path': '/project/source.py'}])
        self.assertEqual(combined.count(HEADER), 1)
        self.assertEqual(unwrap_user_message(combined), ('检查内容', ['/project/source.py', receipt['path']]))
        for route, data in ((f'/api/threads/{T}/operations', {**payload, 'action': 'interrupt'}),
                            (f'/api/threads/{T}/session', payload)):
            with self.assertRaises(ValueError):
                project_request(self.bridge, route, data, None, None)
        with self.assertRaises(BridgeError):
            dispatch(self.bridge, 'POST', '/api/uploads', begin_body(), remote=True, control=False)

    def test_scoped_accounts_include_get_chunk_and_complete_and_creation_has_exact_target(self):
        def request(method, path, data=None, account='account-a'):
            return scoped_dispatch(self.bridge, method, path, data, True, 'binding-a', activity_owner=account)
        receipt = request('POST', '/api/uploads', begin_body())[1]
        self.assertEqual(request('POST', '/api/uploads', chunk_body(receipt['id'], b'hello'))[0], 200)
        self.assertEqual(request('POST', '/api/uploads', {'action': 'complete', 'uploadId': receipt['id']})[1]['target'], TARGET)
        self.assertEqual(request('GET', '/api/uploads/' + receipt['id'])[0], 200)
        with self.assertRaises(BridgeError):
            request('GET', '/api/uploads/' + receipt['id'], account='account-b')
        creation = self.completed(body=begin_body(target={'type': 'creation'}))
        self.assertEqual(creation['target'], {'type': 'creation', 'projectId': None})
        projected = project_request(self.bridge, '/api/threads',
            {'prompt': '', 'uploads': [creation['id']]}, None, None)
        self.assertEqual(unwrap_user_message(projected['prompt']), ('', [creation['path']]))

    def test_capabilities_include_original_and_upload_permissions(self):
        self.assertEqual(required_capabilities('POST', '/api/uploads'), ('send', 'files'))
        self.assertEqual(required_capabilities('GET', '/api/uploads/' + 'a' * 32), ('send', 'files'))
        for route in (f'/api/threads/{T}/compose', f'/api/threads/{T}/messages', f'/api/threads/{T}/operations'):
            self.assertEqual(required_capabilities('POST', route, {'uploads': ['id'], 'action': 'queue-add'}), ('send', 'files'))
        self.assertEqual(required_capabilities('POST', '/api/threads', {'uploads': ['id']}), ('create', 'send', 'files'))
        self.assertEqual(required_capabilities('POST', '/api/threads',
            {'uploads': ['id'], 'settings': {'sandboxPolicy': 'x'}}), ('create', 'edit', 'send', 'files'))


if __name__ == '__main__':
    unittest.main()
