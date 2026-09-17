import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from carryon.onboarding import DEFAULT_CLOUD_URL, command, exchange
from carryon.cloud_manager import CloudManager
from carryon.members_cli import binding
from carryon.catalog import Catalog
from carryon.contracts import settings


class CurrentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict('os.environ', {'CARRYON_REGISTRY_DIR':str(self.root/'registry')})
        self.env.start()
        self.running = patch('carryon.cli.running', return_value=None)
        self.running.start()

    def tearDown(self):
        self.running.stop(); self.env.stop(); self.temp.cleanup()

    def invite(self, url):
        return {'id':'a'*32, 'secret':'b'*43, 'url':url+'/#carryon-bind='+'a'*32+'.'+'c'*43, 'expiresAt':time.time()+300}

    def test_cancel_returns_to_configuration_without_losing_options(self):
        invite = self.invite(DEFAULT_CLOUD_URL)
        with patch('carryon.onboarding.request', return_value=invite):
            exchange(self.root, {'action':'prepare','autoStart':False,'permissions':['view','send']})
        with patch('carryon.onboarding.request', side_effect=OSError('offline')):
            with self.assertRaises(OSError):exchange(self.root, {'action':'cancel'})
        self.assertIn('pending', json.loads((self.root/'onboarding.json').read_text()))
        with patch('carryon.onboarding.request', return_value={'state':'cancelled'}), patch('carryon.onboarding.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):exchange(self.root, {'action':'cancel'})
        self.assertIn('pending', json.loads((self.root/'onboarding.json').read_text()))
        with patch('carryon.onboarding.request', return_value={'state':'cancelled'}) as request:
            state = exchange(self.root, {'action':'cancel'})
            self.assertEqual(request.call_args.args[1], 'cancel')
        self.assertEqual(state['state'], 'configured')
        self.assertIsNone(state['qrURL'])
        self.assertEqual(state['permissions'], ['send','view'])
        self.assertFalse(state['autoStart'])
        with patch('carryon.onboarding.request', return_value=invite):
            self.assertEqual(exchange(self.root, {'action':'prepare','permissions':['view','files']})['state'], 'waiting')

    def test_default_init_needs_no_cloud_address(self):
        self.assertEqual(exchange(self.root, {'action':'status'})['url'], DEFAULT_CLOUD_URL)
        with patch('carryon.onboarding.request', return_value=self.invite(DEFAULT_CLOUD_URL)) as request:
            self.assertEqual(exchange(self.root, {'action':'prepare', 'autoStart':False})['state'], 'waiting')
            self.assertEqual(request.call_args.args[0], DEFAULT_CLOUD_URL)

    def test_desktop_default_selection_does_not_reuse_saved_custom_cloud(self):
        old = {'enabled':True, 'url':'wss://old.test/device', 'deviceId':'mac', 'token':'t'*43, 'control':False}
        path = self.root/'cloud.json'
        path.write_text(json.dumps({'version':2, 'bindings':{'a'*32:old}}))
        before = path.read_bytes()
        (self.root/'onboarding.json').write_text(json.dumps({'state':'bound', 'url':'https://old.test'}))
        with patch('carryon.onboarding.request') as request:
            state = exchange(self.root, {'action':'status','useDefaultCloud':True})
            self.assertEqual(state['url'], DEFAULT_CLOUD_URL)
            self.assertEqual(state['state'], 'configured')
            request.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_cli_does_not_prompt_for_address_or_manual_start(self):
        initial = {'state':'new', 'url':DEFAULT_CLOUD_URL, 'environment':{'supportedPlatform':True,'backend':'app-server'}}
        bound = {'state':'bound', 'autoStart':False}
        args = SimpleNamespace(state_dir=self.root, input_json=False, url=None, permissions=None)
        with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout', new_callable=io.StringIO), patch('builtins.input', side_effect=['n','n']) as inputs, patch('carryon.onboarding.known_accounts', return_value={'accounts':[], 'warnings':[]}), patch('carryon.onboarding.exchange', side_effect=[initial,bound,bound]) as call:
            self.assertEqual(command(args), 0)
            self.assertEqual(inputs.call_count, 2)
            self.assertEqual(call.call_args_list[1].args[1]['url'], DEFAULT_CLOUD_URL)

    def test_new_cloud_does_not_reuse_existing_bound_state(self):
        old = {'enabled':True, 'url':'wss://old.test/device', 'deviceId':'mac', 'token':'t'*43, 'control':False}
        path = self.root/'cloud.json'
        path.write_text(json.dumps({'version':2, 'bindings':{'a'*32:old}}))
        (self.root/'onboarding.json').write_text(json.dumps({'state':'bound', 'url':'https://old.test', 'autoStart':False,'deviceId':'mac','requestId':'old'}))
        before = path.read_bytes()
        with patch('carryon.onboarding.request', return_value=self.invite('https://new.test')) as request:
            result = exchange(self.root, {'action':'prepare', 'url':'https://new.test', 'autoStart':False})
            self.assertEqual(result['state'], 'waiting')
            self.assertEqual(request.call_args.args[:2], ('https://new.test', 'start'))
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(json.loads((self.root/'onboarding.json').read_text())['requestId'], 'old')
        with self.assertRaisesRegex(ValueError, '正在进行'):
            exchange(self.root, {'action':'prepare', 'url':'https://another.test', 'autoStart':False})

    def test_explicit_recovery_cannot_switch_cloud(self):
        old = {'enabled':True, 'url':'wss://old.test/device', 'deviceId':'mac', 'token':'t'*43, 'control':False}
        (self.root/'cloud.json').write_text(json.dumps({'version':2, 'bindings':{'a'*32:old}}))
        with self.assertRaisesRegex(ValueError, '不能更改'):
            exchange(self.root, {'action':'prepare','bindingId':'a'*32,'url':'https://new.test'})

    def test_selecting_new_cloud_does_not_require_old_cloud_online(self):
        old = {'enabled':True, 'url':'wss://old.test/device', 'deviceId':'mac', 'token':'t'*43, 'control':False}
        (self.root/'cloud.json').write_text(json.dumps({'version':2, 'bindings':{'a'*32:old}}))
        (self.root/'onboarding.json').write_text(json.dumps({'state':'bound', 'url':'https://old.test', 'autoStart':False}))
        with patch('carryon.onboarding.request', side_effect=OSError('offline')) as request:
            state = exchange(self.root, {'action':'status','verify':False})
            self.assertEqual(state['state'], 'bound')
            request.assert_not_called()
        with patch('carryon.onboarding.request', return_value=self.invite('https://new.test')) as request:
            self.assertEqual(exchange(self.root, {'action':'prepare', 'url':'https://new.test', 'autoStart':False})['state'], 'waiting')
            self.assertEqual(request.call_args.args[0], 'https://new.test')
        with self.assertRaisesRegex(ValueError, '正在进行'):
            exchange(self.root, {'action':'status','url':'https://old.test'})

    def test_single_cloud_configuration_has_one_read_boundary(self):
        old = {'enabled':True, 'url':'wss://old.test/device', 'deviceId':'mac', 'token':'t'*43, 'control':False}
        path = self.root/'cloud.json'; path.write_text(json.dumps(old)); before = path.read_bytes()
        self.assertEqual(CloudManager.saved_status(self.root)['bindings'][0]['id'], 'legacy')
        self.assertEqual(binding(self.root), ('https://old.test', {'deviceId':'mac','token':'t'*43}))
        self.assertEqual(path.read_bytes(), before)
        path.write_text(json.dumps({'version':3,'enabled':False}))
        with self.assertRaises(ValueError):binding(self.root)
        with self.assertRaises(ValueError):exchange(self.root, {'action':'status'})

    def test_persisted_history_projects_timeline_for_all_clients(self):
        path = self.root/'history.jsonl'
        path.write_text('\n'.join(json.dumps({'type':'response_item','payload':{'type':'message','role':role,'phase':phase,'content':[{'type':'text','text':text}]}}) for role,phase,text in [('user',None,'hello'),('assistant','analysis','private'),('assistant','commentary','working'),('assistant','final','done')]))
        catalog = Catalog(self.root)
        with patch.object(catalog, 'get', return_value={'id':'t','title':'title','cwd':'/tmp','rollout_path':str(path)}):
            history = catalog.history('t')
        self.assertEqual([row['text'] for row in history['timeline']], ['hello','working','done'])
        self.assertEqual(history['timeline'][1]['phase'], 'commentary')
        self.assertNotIn('private', json.dumps(history))

    def test_ignored_native_setting_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, '停用'):
            settings({'multiAgentMode':'explicitRequestOnly'}, 't')
