import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from connectnow.linking import LinkRequests

class LinkHistoryTests(unittest.TestCase):
    def test_results_survive_restart_without_secrets_and_clear_preserves_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            links = LinkRequests(path)
            approved = links.start('Mac'); rejected = links.start('Studio'); pending = links.start('Pending')
            links.approve(approved['id'], 'device')
            links.reject(rejected['id'])
            history = LinkRequests(path).history_snapshot()
            self.assertEqual([r['result'] for r in history], ['rejected', 'approved'])
            raw = path.read_text()
            for request in (approved, rejected):
                self.assertNotIn(request['secret'], raw)
                self.assertNotIn(request['verification'], raw)
            links.clear_history()
            self.assertEqual(json.loads(path.read_text()), [])
            self.assertEqual(links.pending()[0]['id'], pending['id'])
            self.assertEqual(links.poll(approved['id'], approved['secret']), 'device')
            with self.assertRaises(PermissionError): links.poll(rejected['id'], rejected['secret'])
            with self.assertRaises(ValueError): links.reject(rejected['id'])
            self.assertEqual(links.history_snapshot(), [])

    def test_expired_request_archived_once(self):
        links = LinkRequests(); request = links.start('Mac')
        links.entries[request['id']]['expires'] = 0
        self.assertEqual(links.pending(), [])
        self.assertEqual([r['result'] for r in links.history_snapshot()], ['expired'])
        self.assertEqual(len(links.history_snapshot()), 1)

    def test_history_write_failure_does_not_change_authorization_and_clear_failure_keeps_history(self):
        with tempfile.TemporaryDirectory() as directory:
            links = LinkRequests(Path(directory) / 'history.json'); request = links.start('Mac')
            with patch('connectnow.linking.save_json', side_effect=OSError('disk full')):
                links.approve(request['id'], 'device')
                self.assertEqual(links.poll(request['id'], request['secret']), 'device')
                self.assertIsNotNone(links.history_error)
                with self.assertRaises(OSError): links.clear_history()
            self.assertEqual(len(links.history_snapshot()), 1)

    def test_corrupt_history_does_not_block_new_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            for raw in ('{broken', '[{"id":"bad"}]', '{}'):
                path.write_text(raw)
                links = LinkRequests(path)
                self.assertIsNotNone(links.history_error)
                self.assertEqual(links.history_snapshot(), [])
                self.assertIsNotNone(links.start('Mac')['id'])

    def test_history_whitelist_and_retention_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            record = {'id':'old','name':'Mac','created':1,'resolvedAt':2,'result':'approved','secret':'private'}
            path.write_text(json.dumps([record] * 1005))
            links = LinkRequests(path)
            self.assertEqual(len(links.history_snapshot()), 1000)
            self.assertNotIn('secret', links.history_snapshot()[0])
            request = links.start('New'); links.reject(request['id'])
            self.assertEqual(len(links.history_snapshot()), 1000)
            self.assertEqual(links.history_snapshot()[0]['name'], 'New')
            self.assertNotIn('private', path.read_text())
