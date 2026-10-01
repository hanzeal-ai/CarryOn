"""Opt-in native queue observations: private home, localhost model, no scheduler."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from run_appserver_regression import Model, wait_until
from carryon.app_server.app_server import AppServer


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeQueueIntegration(unittest.TestCase):
    def test_installed_native_queue_lifecycle(self):
        gate = threading.Event(); entered = threading.Event()
        class GatedModel(Model):
            def do_POST(self):
                entered.set(); gate.wait(15)
                try: super().do_POST()
                except (BrokenPipeError, ConnectionResetError): pass
        model = ThreadingHTTPServer(('127.0.0.1', 0), GatedModel)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        observations = {}
        with tempfile.TemporaryDirectory(prefix='carryon-native-queue-contract-') as directory:
            root = Path(directory); home = root / 'codex'; home.mkdir()
            (home / 'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n'
                '[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:' +
                str(model.server_port) + '/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
            runtime = AppServer(home)
            def create():
                return runtime.create_thread({'cwd': str(root), 'historyMode': 'paginated'}, lambda write: write())['id']
            def rows(tid): return runtime.rpc('thread/queue/list', {'threadId': tid})
            def add(tid, key):
                return runtime.rpc('thread/queue/add', {'threadId': tid, 'clientUserMessageId': key,
                    'input': [{'type': 'text', 'text': 'fixture ' + key}]})['queuedSubmission']
            def completed(tid, key):
                return any(t['status'] == 'completed' and any(i.get('clientId') == key for i in t['items'])
                           for t in runtime.current(tid)['turns'])
            def block(tid, key):
                gate.clear(); entered.clear()
                result = runtime.rpc('turn/start', {'threadId': tid, 'clientUserMessageId': key,
                    'input': [{'type': 'text', 'text': 'fixture blocked'}]})
                self.assertTrue(entered.wait(5))
                return result['turn']['id']
            try:
                runtime.connect()
                tid = create(); block(tid, 'active-seed'); added = add(tid, 'active-queued')
                observations['activeStored'] = rows(tid)
                self.assertEqual(observations['activeStored']['data'][0]['id'], added['id'])
                gate.set(); wait_until(lambda: completed(tid, 'active-queued'))
                observations['activeAutomaticallyConsumed'] = rows(tid)
                self.assertEqual(observations['activeAutomaticallyConsumed']['data'], [])
                tid = create(); gate.set(); idle = add(tid, 'idle-queued'); time.sleep(.3)
                observations['idleAfterAdd'] = {'queue': rows(tid), 'completed': completed(tid, 'idle-queued')}
                if observations['idleAfterAdd']['queue']['data']:
                    observations['idleExplicitStart'] = runtime.rpc('thread/queue/start', {'threadId': tid, 'queuedSubmissionId': idle['id']})
                wait_until(lambda: completed(tid, 'idle-queued'))
                tid = create(); active = block(tid, 'interrupt-seed')
                a, b, c = [add(tid, key) for key in ('queued-a', 'queued-b', 'queued-c')]
                updated = runtime.rpc('thread/queue/update', {'threadId': tid, 'queuedSubmissionId': b['id'],
                    'input': [{'type': 'text', 'text': 'fixture edited'}]})
                runtime.rpc('thread/queue/reorder', {'threadId': tid, 'queuedSubmissionIds': [c['id'], b['id'], a['id']]})
                deleted = runtime.rpc('thread/queue/delete', {'threadId': tid, 'queuedSubmissionId': a['id']})
                self.assertTrue(deleted['deleted'])
                observations['editedWhileActive'] = rows(tid)
                self.assertEqual([v['id'] for v in observations['editedWhileActive']['data']], [c['id'], b['id']])
                self.assertEqual(updated['queuedSubmission']['input'][0]['text'], 'fixture edited')
                runtime.rpc('turn/interrupt', {'threadId': tid, 'turnId': active})
                wait_until(lambda: any(t['turnId'] == active and t['status'] == 'interrupted' for t in runtime.current(tid)['turns']))
                time.sleep(.15); observations['afterInterruptBeforeModelRelease'] = rows(tid)
                gate.set(); time.sleep(.3)
                observations['afterInterrupt'] = {'queue': rows(tid), 'turns': [
                    {'id': t['turnId'], 'status': t['status']} for t in runtime.current(tid)['turns']]}
                remaining = observations['afterInterrupt']['queue']['data']
                if remaining:
                    observations['explicitStartAfterInterrupt'] = runtime.rpc('thread/queue/start',
                        {'threadId': tid, 'queuedSubmissionId': remaining[0]['id']})
                    wait_until(lambda: completed(tid, remaining[0]['clientUserMessageId']))
                observations['finalQueue'] = rows(tid)
                print('\nNATIVE_QUEUE_OBSERVATIONS=' + json.dumps(observations, ensure_ascii=False))
            finally:
                gate.set(); runtime.close(); model.shutdown(); model.server_close()
