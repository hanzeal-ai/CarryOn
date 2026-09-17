import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from carryon.onboarding import exchange, InvalidDeviceCredentials
from carryon.cloud_manager import CloudManager
import test_console_auth


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = {'enabled':True,'url':'wss://example.test/device','deviceId':'old','token':'o'*43,'control':False}
        self.other = {**self.old,'url':'wss://other.test/device','deviceId':'other','token':'x'*43}
        (self.root/'cloud.json').write_text(json.dumps({'version':2,'bindings':{'a'*32:self.old,'b'*32:self.other}}))
        (self.root/'onboarding.json').write_text(json.dumps({'state':'bound','url':'https://example.test','autoStart':False}))
        self.env = patch.dict('os.environ', {'CARRYON_REGISTRY_DIR':str(self.root/'registry')}); self.env.start()
        self.running = patch('carryon.cli.running',return_value=None); self.running.start()

    def tearDown(self):
        self.running.stop(); self.env.stop(); self.temp.cleanup()

    def test_invalid_credentials_enable_recovery_without_deleting_config(self):
        before = (self.root/'cloud.json').read_bytes()
        with patch('carryon.onboarding.request',side_effect=InvalidDeviceCredentials('invalid')):
            result = exchange(self.root, {'action':'status'})
        self.assertEqual(result['state'],'configured')
        self.assertEqual(result['url'],'https://example.test')
        self.assertNotIn('replacement',result)
        self.assertEqual((self.root/'cloud.json').read_bytes(),before)

    def test_network_failure_is_unknown_not_rebind_and_prepare_is_blocked(self):
        before = (self.root/'onboarding.json').read_bytes()
        with patch('carryon.onboarding.request',side_effect=TimeoutError('offline')):
            result = exchange(self.root, {'action':'status'})
            self.assertEqual(result['state'],'unverified')
            with self.assertRaisesRegex(ValueError,'暂时无法验证'):
                exchange(self.root, {'action':'prepare','url':'https://example.test'})
        self.assertEqual((self.root/'onboarding.json').read_bytes(),before)

    def test_valid_legacy_saved_config_requires_cloud_validation(self):
        (self.root/'onboarding.json').unlink()
        (self.root/'cloud.json').write_text(json.dumps({'version':2,'bindings':{'a'*32:self.old}}))
        with patch('carryon.onboarding.request',return_value={'members':[]}) as request:
            self.assertEqual(exchange(self.root, {'action':'status'})['state'],'bound')
        self.assertEqual(request.call_args.args[1],'manage')

    def test_ambiguous_multiple_clouds_require_selection_without_network_or_mutation(self):
        (self.root/'onboarding.json').unlink()
        before=(self.root/'cloud.json').read_bytes()
        with patch('carryon.onboarding.request') as request:
            result=exchange(self.root,{'action':'status'})
            self.assertEqual(result['state'],'unverified')
            self.assertIn('请选择',result['error'])
            request.assert_not_called()
        self.assertEqual((self.root/'cloud.json').read_bytes(),before)
        with patch('carryon.onboarding.request',return_value={'members':[]}):
            self.assertEqual(exchange(self.root,{'action':'status','bindingId':'b'*32})['url'],'https://other.test')

    def test_explicit_apply_does_not_rebase_without_new_credential_verification(self):
        state={'state':'confirming','url':'https://example.test','control':False,
               'replacement':{'id':'a'*32,'fingerprint':'old-fingerprint'},
               'pending':{'expiresAt':0,'confirmed':{'state':'bound','deviceId':'new','token':'n'*43}}}
        (self.root/'onboarding.json').write_text(json.dumps(state))
        before=(self.root/'cloud.json').read_bytes()
        for failure in (TimeoutError('offline'),InvalidDeviceCredentials('revoked')):
            with self.subTest(failure=type(failure).__name__), patch('carryon.onboarding.request',side_effect=failure):
                with self.assertRaises((OSError,ValueError)):
                    exchange(self.root,{'action':'apply-confirmed'})
            self.assertEqual(json.loads((self.root/'onboarding.json').read_text()),state)
            self.assertEqual((self.root/'cloud.json').read_bytes(),before)

    def test_replacement_is_targeted_idempotent_and_refuses_changed_identity(self):
        manager = CloudManager(None,self.root)
        replacement = {'id':'a'*32,'fingerprint':manager.fingerprint(self.old)}
        updated = {**self.old,'deviceId':'new','token':'n'*43,'replacement':replacement}
        manager.configure(updated,start=False)
        manager.configure(updated,start=False)
        saved = json.loads((self.root/'cloud.json').read_text())['bindings']
        self.assertEqual(saved['a'*32]['deviceId'],'new')
        self.assertNotIn('replacement',saved['a'*32])
        self.assertEqual(saved['b'*32],self.other)
        with self.assertRaisesRegex(ValueError,'原绑定已改变'):
            manager.configure({**updated,'deviceId':'another'},start=False)
        with self.assertRaisesRegex(ValueError,'其他云端'):
            manager.configure({**updated,'url':'wss://elsewhere.test/device'},start=False)

    def test_persistence_failure_retains_original_connection_and_disk(self):
        manager=CloudManager(None,self.root)
        original=manager.connections['a'*32]; before=(self.root/'cloud.json').read_bytes()
        updated={**self.old,'deviceId':'new','token':'n'*43,
                 'replacement':{'id':'a'*32,'fingerprint':manager.fingerprint(self.old)}}
        with patch.object(manager,'_save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):manager.configure(updated,start=False)
        self.assertIs(manager.connections['a'*32],original)
        self.assertEqual((self.root/'cloud.json').read_bytes(),before)

    def test_running_install_uses_guarded_replacement_and_stop_failure_preserves_original(self):
        from carryon.onboarding import install_binding
        from types import SimpleNamespace
        manager=CloudManager(SimpleNamespace(),self.root)
        original=manager.connections['a'*32]
        updated={**self.old,'deviceId':'new','token':'n'*43}
        replacement={'id':'a'*32,'fingerprint':manager.fingerprint(self.old)}
        before=(self.root/'cloud.json').read_bytes()
        with patch.object(original,'stop',side_effect=ValueError('still running')):
            with self.assertRaisesRegex(ValueError,'still running'):
                manager.configure({**updated,'replacement':replacement})
        self.assertIs(manager.connections['a'*32],original)
        self.assertEqual((self.root/'cloud.json').read_bytes(),before)
        def call(directory,path,body,timeout):
            self.assertEqual(path,'/cloud')
            return manager.configure(body)
        with patch('carryon.cli.running',return_value={'port':1234}), patch('carryon.cli.call',side_effect=call), patch('carryon.cloud.CloudConnector.start'), patch('carryon.cloud.CloudConnector.stop'):
            install_binding(self.root,updated,replacement)
        self.assertEqual(manager.connections['a'*32].config['deviceId'],'new')
        self.assertEqual(manager.connections['b'*32].config,self.other)


class RecoveryFlowTests(unittest.TestCase):
    # Reuse the existing real HTTP console fixture, without inheriting its test cases.
    setUpClass = classmethod(test_console_auth.AccountTests.setUpClass.__func__)
    setUp = test_console_auth.AccountTests.setUp
    start = test_console_auth.AccountTests.start
    stop = test_console_auth.AccountTests.stop
    tearDown = test_console_auth.AccountTests.tearDown
    request = test_console_auth.AccountTests.request

    def test_scan_confirmation_replaces_invalid_binding_and_preserves_other_cloud(self):
        self.server.public_url='https://example.test'
        root=Path(self.temp.name)/'local'; root.mkdir()
        old={'enabled':True,'url':'wss://example.test/device','deviceId':'missing','token':'o'*43,'control':False}
        other={**old,'url':'wss://other.test/device','deviceId':'other'}
        (root/'cloud.json').write_text(json.dumps({'version':2,'bindings':{'a'*32:old,'b'*32:other}}))
        (root/'onboarding.json').write_text(json.dumps({'state':'bound','url':'https://example.test','autoStart':False}))
        def rpc(url,action,body):
            self.assertEqual(url,'https://example.test')
            status,value,_=self.request('binding/'+action,body,origin=False)
            if status==403 and value.get('error')=='设备凭证无效':raise InvalidDeviceCredentials(value['error'])
            if status!=200:raise ValueError(value)
            return value
        with patch.dict('os.environ',{'CARRYON_REGISTRY_DIR':str(root/'registry')}), patch('carryon.cli.running',return_value=None), patch('carryon.onboarding.request',side_effect=rpc):
            self.assertEqual(exchange(root,{'action':'status'})['state'],'configured')
            initial=(root/'cloud.json').read_bytes()
            prepared=exchange(root,{'action':'prepare','url':'https://example.test','autoStart':False})
            self.assertEqual(prepared['state'],'waiting')
            self.assertEqual((root/'cloud.json').read_bytes(),initial)
            self.assertEqual(exchange(root,{'action':'status'})['qrURL'],prepared['qrURL'])
            self.assertEqual(exchange(root,{'action':'poll'})['state'],'waiting')
            ident,scan=prepared['qrURL'].split('#carryon-bind=')[1].split('.')
            status,_,cookie=self.request('register',{'username':'alice','password':'a long password 123',**self.server.auth.create_registration_invite()})
            self.assertEqual(status,200)
            self.assertEqual(self.request('binding/accept',{'id':ident,'secret':scan},cookie)[0],200)
            changed={**old,'token':'c'*43}
            (root/'cloud.json').write_text(json.dumps({'version':2,'bindings':{'a'*32:changed,'b'*32:other}}))
            conflict=exchange(root,{'action':'poll'})
            self.assertEqual(conflict['state'],'confirming')
            self.assertIsNone(conflict['qrURL'])
            self.assertNotIn('token',json.dumps(conflict))
            state=json.loads((root/'onboarding.json').read_text())
            self.assertIn('token',state['pending']['confirmed'])
            state['pending']['expiresAt']=0
            (root/'onboarding.json').write_text(json.dumps(state))
            self.assertEqual(exchange(root,{'action':'status'})['state'],'confirming')
            self.assertEqual(exchange(root,{'action':'poll'})['state'],'confirming')
            self.assertEqual(json.loads((root/'cloud.json').read_text())['bindings']['a'*32],changed)
            # The user's explicit desktop action resolves the conflict, without editing files.
            bound=exchange(root,{'action':'apply-confirmed'})
            self.assertEqual(bound['state'],'bound')
            self.assertEqual(exchange(root,{'action':'poll'})['state'],'bound')
            saved=json.loads((root/'cloud.json').read_text())['bindings']
            self.assertEqual(set(saved),{'a'*32,'b'*32})
            self.assertEqual(saved['b'*32],other)
            self.assertNotEqual(saved['a'*32]['token'],old['token'])
            self.assertIn(saved['a'*32]['deviceId'],self.server.config['devices'])
