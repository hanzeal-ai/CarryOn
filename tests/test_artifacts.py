import base64
from pathlib import Path
import tempfile
import unittest
from carryon.artifacts import references, read_artifact
from carryon.images import image_id
from carryon.errors import BridgeError
from carryon.bridge import snapshot_history


class ArtifactTests(unittest.TestCase):
    def test_output_reference_projection_and_bounded_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'my report.md'
            path.write_text('# result')
            native = {'id': 'test', 'turns': [{'turnId': 't', 'items': [{'type': 'agentMessage', 'text': f'[报告](<{path}>)'}]}]}
            history = snapshot_history(native)
            ref = history['timeline'][1]['artifacts'][0]
            self.assertEqual(ref['path'], str(path))
            self.assertEqual(base64.b64decode(read_artifact(history, ref['id'])['base64']), b'# result')
            with self.assertRaises(BridgeError): read_artifact(history, image_id('/etc/passwd'))
            with self.assertRaises(BridgeError): read_artifact({'timeline': []}, ref['id'])
            path.unlink(); path.symlink_to('/etc/passwd')
            with self.assertRaises(BridgeError): read_artifact(history, ref['id'])
            path.unlink(); path.write_bytes(b'x' * (8 * 1024 * 1024 + 1))
            with self.assertRaises(ValueError): read_artifact(history, ref['id'])

    def test_only_explicit_displayed_outputs_become_files(self):
        self.assertEqual(references('userMessage', {'text': '[x](/etc/passwd)'}), [])
        self.assertEqual(references('agentMessage', {'text': '[x](javascript:alert) [x](https://example.test/a)'}), [])
        ref = references('imageView', {'path': '/tmp/result.png'})[0]
        self.assertEqual(ref['kind'], 'image')
        self.assertEqual(references('agentMessage', {'text': '[x](/tmp/a.py:12)'})[0]['path'], '/tmp/a.py')


class ArtifactCloudTests(unittest.TestCase):
    import test_cloud as fixture
    setUp = fixture.CloudTests.setUp
    tearDown = fixture.CloudTests.tearDown
    wait = fixture.CloudTests.wait
    connect = fixture.CloudTests.connect
    call = fixture.CloudTests.call
    request = fixture.CloudTests.request

    def test_readonly_attachment_route_is_history_scoped_and_revoked_with_bridge(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'result.txt'; path.write_text('result')
            self.bridge.history = lambda tid: {'timeline': [{'type': 'agentMessage', 'data': {'text': f'[result]({path})'}}]}
            self.bridge.enable(); self.connect()
            route = '/api/threads/' + self.fixture.T + '/artifacts/'
            status, result = self.request('GET', route + image_id(str(path)))
            self.assertEqual(status, 200)
            self.assertEqual(base64.b64decode(result['base64']), b'result')
            self.assertEqual(self.request('GET', route + '0' * 64)[0], 404)
            self.assertEqual(self.request('POST', route + image_id(str(path)), {})[0], 403)
            self.bridge.disable()
            self.assertEqual(self.request('GET', route + image_id(str(path)))[0], 403)
