"""Real app-server + localhost WebSocket; private credentials, no model tasks."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest

from carryon.app_server.app_server_bridge import AppServerBridge
from carryon.app_server.app_server import AppServer
from carryon.routes.api import dispatch
from carryon.store import Journal
from run_appserver_regression import wait_until


class RealtimeFixture:
    def __init__(self, reject=False):
        self.reject = reject; self.frames = []; self.closed = threading.Event()
        self.server = socket.socket(); self.server.bind(('127.0.0.1', 0)); self.server.listen()
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
    def run(self):
        try: connection, _ = self.server.accept()
        except OSError: self.closed.set(); return
        connection.settimeout(10)
        def receive(size):
            data = b''
            while len(data) < size:
                part = connection.recv(size - len(data))
                if not part: raise EOFError()
                data += part
            return data
        try:
            headers = b''
            while b'\r\n\r\n' not in headers: headers += connection.recv(4096)
            if self.reject:
                connection.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'); return
            key = next(line.split(b':', 1)[1].strip() for line in headers.split(b'\r\n') if line.lower().startswith(b'sec-websocket-key:'))
            accept = base64.b64encode(hashlib.sha1(key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
            connection.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
            def send(event):
                data = json.dumps(event).encode()
                connection.sendall(bytes([129, 126]) + struct.pack('!H', len(data)) + data)
            send({'type': 'session.created', 'session': {'id': 'fixture'}})
            while True:
                header = receive(2); size = header[1] & 127
                if size == 126: size = struct.unpack('!H', receive(2))[0]
                elif size == 127: size = struct.unpack('!Q', receive(8))[0]
                mask = receive(4) if header[1] & 128 else None; payload = receive(size)
                if mask: payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
                if header[0] & 15 == 8: break
                event = json.loads(payload)
                # Native startup context is neither needed nor retained by this fixture.
                event.get('session', {}).pop('instructions', None)
                self.frames.append(event)
                if event['type'] == 'session.update':
                    send({'type': 'session.updated', 'session': {'id': 'fixture'}})
                    send({'type': 'response.audio.delta', 'delta': 'AAAAAA==', 'item_id': 'fixture-item', 'response_id': 'fixture-response', 'output_index': 0, 'content_index': 0})
                    send({'type': 'response.output_audio_transcript.delta', 'delta': 'fixture speech', 'item_id': 'fixture-item', 'response_id': 'fixture-response', 'output_index': 0, 'content_index': 0})
                    send({'type': 'response.output_audio_transcript.done', 'transcript': 'fixture speech', 'item_id': 'fixture-item', 'response_id': 'fixture-response', 'output_index': 0, 'content_index': 0})
        except (EOFError, OSError): pass
        finally: connection.close(); self.closed.set()
    def close(self):
        self.server.close(); self.thread.join(2)


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeVoiceIntegration(unittest.TestCase):
    def exercise(self, reject):
        fixture = RealtimeFixture(reject)
        with tempfile.TemporaryDirectory(prefix='carryon-native-voice-') as directory:
            root = Path(directory); home = root / 'home'; home.mkdir()
            (home / 'auth.json').write_text('{"OPENAI_API_KEY":"fixture-not-real"}')
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\nexperimental_realtime_ws_base_url="ws://127.0.0.1:' + str(fixture.port) + '"\ncli_auth_credentials_store="file"\n[model_providers.fixture]\nname="Fixture"\nbase_url="http://127.0.0.1:9/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            journal = Journal(root / 'jobs.sqlite'); bridge = AppServerBridge(home, journal)
            # This fixture owns its private API key and must never borrow the desktop account.
            bridge.ipc_factory = AppServer
            try:
                bridge.enable(); runtime = bridge.ipc
                tid = runtime.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda write: write())['id']
                path = '/api/threads/' + tid
                _, job = dispatch(bridge, 'POST', path + '/operations', {'action': 'voice-start', 'requestId': 'fixture-voice-start'})
                self.assertEqual(job['state'], 'completed', job)
                identifier = job['result']['voiceId']
                expected = 'unknown' if reject else 'active'
                wait_until(lambda: runtime.current(tid).get('voice', {}).get('state') == expected)
                _, read = dispatch(bridge, 'GET', path + '/voice')
                self.assertEqual(read['voice']['id'], identifier)
                if not reject:
                    wait_until(lambda: len(runtime.voice_channels[tid]['events']) >= 3)
                    _, read = dispatch(bridge, 'GET', path + '/voice')
                    self.assertEqual({row['type'] for row in read['events']}, {'outputAudio/delta', 'transcript/delta', 'transcript/done'})
                    stream=bridge.open_stream()
                    try:
                        stream.subscribe({'type':'subscribe','subscription':'native-voice','threadId':tid,'voiceId':identifier})
                        packet=stream.update()[0]['voice']
                        self.assertEqual(packet['events'],read['events'])
                        stream.ack_voice({'subscription':'native-voice','voiceId':identifier,'after':packet['sequence']})
                        self.assertEqual(stream.update()[0]['voice']['events'],[])
                    finally: stream.close()
                    _, ack = dispatch(bridge, 'POST', path + '/voice/audio', {'voiceId': identifier, 'sequence': 1, 'audio': {'data': 'AAAAAA==', 'sampleRate': 24000, 'numChannels': 1, 'samplesPerChannel': 2}})
                    self.assertTrue(ack['accepted'])
                    wait_until(lambda: any(frame['type'] == 'input_audio_buffer.append' for frame in fixture.frames))
                    _, duplicate = dispatch(bridge, 'POST', path + '/operations', {'action': 'voice-start', 'requestId': 'fixture-voice-start'})
                    self.assertEqual(duplicate['result']['voiceId'], identifier)
                    _, overlap = dispatch(bridge, 'POST', path + '/operations', {'action': 'voice-start', 'requestId': 'fixture-voice-overlap'})
                    self.assertEqual(overlap['state'], 'failed')
                    self.assertEqual(sum(frame['type'] == 'session.update' for frame in fixture.frames), 1)
                _, stop = dispatch(bridge, 'POST', path + '/operations', {'action': 'voice-stop', 'requestId': 'fixture-voice-stop', 'voiceId': identifier})
                self.assertEqual(stop['state'], 'completed', stop)
                wait_until(lambda: runtime.current(tid)['voice']['state'] == 'closed')
                self.assertTrue(runtime.current(tid)['voice']['closed'])
                self.assertFalse(any(item.get('type', '').startswith('transcript') for turn in runtime.current(tid)['turns'] for item in turn['items']))
            finally: bridge.disable(); journal.conn.close(); fixture.close()
    def test_audio_transcript_lifecycle_and_idempotency(self): self.exercise(False)
    def test_async_start_rejection_then_stop_closes(self): self.exercise(True)
