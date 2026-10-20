"""HTTP and outbound tunnel exercise actual routing using disposable fixture state."""
import http.client
import json
import threading
import unittest

import test_cloud
import test_console
import test_project_creation
import test_uploads
from test_uploads import begin_body, chunk_body, T
from carryon.server import Server, Handler
from carryon.sessions.user_messages import unwrap_user_message
from carryon.uploads import LIMITS
from carryon.routes.api import dispatch
from carryon.uploads import Uploads


class UploadHTTPTests(unittest.TestCase):
    setUp = test_uploads.UploadTests.setUp
    tearDown = test_uploads.UploadTests.tearDown

    def test_http_limit_auth_and_static_asset(self):
        server = Server(('127.0.0.1', 0), Handler)
        server.token = 'a' * 43
        server.bridge = self.bridge
        server.allowed_hosts = {f'127.0.0.1:{server.server_port}'}
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def request(method, path, data=None, authorized=True):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=4)
            headers = {'Content-Type': 'application/json'}
            if authorized:
                headers['Authorization'] = 'Bearer ' + server.token
            connection.request(method, path, json.dumps(data) if data is not None else None, headers)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result
        try:
            data = b'x' * LIMITS['chunkBytes']
            self.assertEqual(request('POST', '/api/uploads', begin_body(data), False)[0], 401)
            status, raw = request('POST', '/api/uploads', begin_body(data))
            self.assertEqual(status, 200); identifier = json.loads(raw)['id']
            self.assertEqual(request('POST', '/api/uploads', chunk_body(identifier, data))[0], 200)
            self.assertEqual(request('POST', '/api/uploads', chunk_body(identifier, data + b'x'))[0], 400)
            self.assertEqual(request('POST', '/api/uploads', {'padding': 'x' * 100001})[0], 400)
            status, raw = request('POST', '/api/uploads', {'action': 'complete', 'uploadId': identifier})
            self.assertEqual(status, 200); self.assertEqual(json.loads(raw)['state'], 'complete')
            self.assertEqual(request('GET', '/file-uploads.js', authorized=False)[0], 200)
            self.assertEqual(request('GET', '/attachments/' + identifier, authorized=False)[0], 401)
        finally:
            server.shutdown(); server.server_close(); worker.join(3)


class UploadCloudTests(unittest.TestCase):
    setUp = test_cloud.CloudTests.setUp
    tearDown = test_cloud.CloudTests.tearDown
    wait = test_cloud.CloudTests.wait
    connect = test_cloud.CloudTests.connect
    call = test_cloud.CloudTests.call
    request = test_cloud.CloudTests.request

    def test_tunnel_chunk_replay_and_existing_dispatch_idempotency(self):
        sent = []
        class UploadIPC(test_cloud.IPC):
            def start(self, tid, prompt, owner, mid, before_send):
                before_send(lambda: sent.append(prompt))
                return {'id': 'upload-turn'}
        self.bridge.workspace_directory = self.path
        self.bridge.ipc_factory = UploadIPC
        self.bridge.enable(); self.connect()
        data = b'x' * LIMITS['chunkBytes']
        body = begin_body(data)
        self.assertEqual(self.request('POST', '/api/uploads', body)[0], 403)
        self.connect(control=True)
        status, state = self.request('GET', '/api/status')
        self.assertTrue(state['supportsUploads'])
        self.assertEqual(state['uploadLimits'], LIMITS)
        status, receipt = self.request('POST', '/api/uploads', body)
        self.assertEqual(status, 200)
        chunk = chunk_body(receipt['id'], data)
        self.assertEqual(self.request('POST', '/api/uploads', chunk), (200, {'offset': len(data)}))
        self.assertEqual(self.request('POST', '/api/uploads', chunk), (200, {'offset': len(data)}))
        status, receipt = self.request('POST', '/api/uploads', {'action': 'complete', 'uploadId': receipt['id']})
        self.assertEqual(status, 200)
        payload = {'requestId': 'upload-send-request', 'prompt': 'read file', 'uploads': [receipt['id']]}
        route = '/api/threads/' + T + '/messages'
        self.assertEqual(self.request('POST', route, payload)[0], 202)
        self.wait(lambda: len(sent) == 1)
        self.assertEqual(unwrap_user_message(sent[0]), ('read file', [receipt['path']]))
        self.assertEqual(self.request('POST', route, payload)[0], 202)
        self.assertEqual(len(sent), 1)
        self.connect(control=False)
        self.assertEqual(self.request('GET', '/api/uploads/' + receipt['id'])[0], 403)
        self.assertEqual(self.request('POST', '/api/uploads', chunk)[0], 403)


class UploadCreationTests(unittest.TestCase):
    setUp = test_project_creation.ProjectCreationTests.setUp
    tearDown = test_project_creation.ProjectCreationTests.tearDown
    settled = test_project_creation.ProjectCreationTests.settled

    def test_uploaded_file_reaches_existing_native_creation_once(self):
        self.bridge.workspace_directory = self.home / 'service-state'
        self.bridge.workspace_directory.mkdir()
        uploader = Uploads(self.bridge)
        body = begin_body(target={'type': 'creation', 'projectId': self.project})
        receipt = uploader.begin(body)
        uploader.chunk(chunk_body(receipt['id'], b'hello'))
        receipt = uploader.complete({'uploadId': receipt['id']})
        payload = {'requestId': 'upload-create-request', 'projectId': self.project,
                   'prompt': '', 'uploads': [receipt['id']]}
        status, job = dispatch(self.bridge, 'POST', '/api/threads', payload)
        self.assertEqual(status, 202)
        self.assertEqual(self.settled(job)['state'], 'completed')
        runtime = test_project_creation.Creator.instances[0]
        text = runtime.calls[1][1]['input'][0]['text']
        self.assertEqual(unwrap_user_message(text), ('', [receipt['path']]))
        self.assertEqual(dispatch(self.bridge, 'POST', '/api/threads', payload)[0], 202)
        self.assertEqual(len(test_project_creation.Creator.instances), 1)
        self.assertEqual(len([call for call in runtime.calls if call[0] == 'turn/start']), 1)


class UploadConsoleTests(unittest.TestCase):
    setUp = test_console.ConsoleTests.setUp
    tearDown = test_console.ConsoleTests.tearDown
    configure_device = test_console.ConsoleTests.configure_device
    device_config = test_console.ConsoleTests.device_config
    login = test_console.ConsoleTests.login
    call = test_console.ConsoleTests.call
    wait = test_cloud.CloudTests.wait

    def test_verified_account_and_live_capabilities_gate_every_upload_step(self):
        self.bridge.workspace_directory = self.root
        self.connector.binding_id = 'fixture-upload-binding'
        self.login()
        self.configure_device({**self.device_config(), 'control': True})
        self.bridge.enable()
        self.wait(lambda: self.connector.status()['connected'])
        route = '/console/devices/my-mac/request'
        def request(method, path, data=None):
            return self.call('POST', route, {'method': method, 'path': path, 'body': data})
        record = self.server.config['devices']['my-mac']
        record['members']['owner'] = ['view', 'send']
        self.assertEqual(request('POST', '/api/uploads', begin_body())[0], 403)
        record['members']['owner'] = ['view', 'files']
        self.assertEqual(request('POST', '/api/uploads', begin_body())[0], 403)
        record['members']['owner'] = ['view', 'send', 'files']
        status, receipt, _ = request('POST', '/api/uploads', begin_body())
        self.assertEqual(status, 200)
        chunk = chunk_body(receipt['id'], b'hello')
        self.assertEqual(request('POST', '/api/uploads', chunk)[0], 200)
        record['members']['owner'] = ['view', 'files']
        self.assertEqual(request('POST', '/api/uploads', {'action': 'complete', 'uploadId': receipt['id']})[0], 403)
        self.assertEqual(request('GET', '/api/uploads/' + receipt['id'])[0], 403)
        record['members']['owner'] = ['view', 'send', 'files']
        self.assertEqual(request('POST', '/api/uploads', {'action': 'complete', 'uploadId': receipt['id']})[0], 200)
        self.assertEqual(request('GET', '/api/uploads/' + receipt['id'])[0], 200)
        self.assertEqual(request('POST', '/api/threads',
            {'requestId': 'missing-create-grant', 'prompt': '', 'uploads': [receipt['id']]})[0], 403)


if __name__ == '__main__':
    unittest.main()
