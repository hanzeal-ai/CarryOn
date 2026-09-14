import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from carryon.cli import main

ROOT=Path(__file__).resolve().parent.parent

class CLITests(unittest.TestCase):
    def test_cloud_connect_requests_confirmation_for_each_state_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            for name,control in [('a',False),('b',True)]:
                state=Path(temp)/name
                output=io.StringIO()
                args=['cloud','connect','--state-dir',str(state),'--url','https://example.test/carryon']
                if control:args.append('--allow-control')
                with patch('carryon.cli.running',return_value={'port':1234}), patch('carryon.cli.call',return_value={
                        'id':'request-id','verification':'ABC123','url':'https://example.test/carryon/#connect=request-id'}) as call, \
                        patch('carryon.cli.getpass.getpass') as prompt, redirect_stdout(output):
                    self.assertEqual(main(args),0)
                call.assert_called_once_with(state.resolve(),'/cloud/link/start',
                    {'url':'https://example.test/carryon','control':control},timeout=20)
                prompt.assert_not_called()
                self.assertIn('ABC123',output.getvalue())
                self.assertIn('https://example.test/carryon/#connect=request-id',output.getvalue())
                self.assertIn('申请已提交',output.getvalue())

    def test_cloud_connect_requires_running_service_and_valid_options(self):
        for running,options,error in [(None,['--url','https://example.test'],'服务未运行'),
                ({'port':1234},[],'需要 --url'),
                ({'port':1234},['--url','https://example.test','--token-file','unused'],'需要 --device-id'),
                ({'port':1234},['--url','http://localhost','--dev-local'],'需要 --device-id')]:
            with self.subTest(options=options), patch('carryon.cli.running',return_value=running), \
                    patch('carryon.cli.call') as call, patch('carryon.cli.getpass.getpass') as prompt, \
                    redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(['cloud','connect']+options),1)
                self.assertIn(error,output.getvalue())
                call.assert_not_called();prompt.assert_not_called()

    def test_cloud_connect_request_error_does_not_claim_success(self):
        with patch('carryon.cli.running',return_value={'port':1234}), \
                patch('carryon.cli.call',side_effect=ValueError('云端连接授权失败')), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(['cloud','connect','--url','https://example.test']),1)
        self.assertEqual(output.getvalue(),'')
        self.assertIn('云端连接授权失败',error.getvalue())

    def test_cloud_connect_existing_credentials_remain_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            token=Path(temp)/'device-token';token.write_text('d'*40)
            with patch('carryon.cli.running',return_value={'port':1234}), \
                    patch('carryon.cli.call',return_value={}) as call, redirect_stdout(io.StringIO()):
                self.assertEqual(main(['cloud','connect','--state-dir',temp,'--url','wss://example.test/device',
                    '--device-id','my-mac','--token-file',str(token),'--allow-control']),0)
            call.assert_called_once_with(Path(temp).resolve(),'/cloud',{'enabled':True,'url':'wss://example.test/device',
                'deviceId':'my-mac','token':'d'*40,'control':True,'devLocal':False})

    def test_start_reuse_assets_and_authenticated_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state';codex=Path(temp)/'empty-codex';codex.mkdir()
            env=dict(os.environ,CARRYON_REGISTRY_DIR=str(Path(temp)/'registry'))
            binary=os.environ.get('CARRYON_TEST_EXECUTABLE')
            if binary:env.pop('PYTHONPATH',None)
            else:env['PYTHONPATH']=str(ROOT)
            command=[binary] if binary else [sys.executable,'-m','carryon']
            def run(*args):return subprocess.run(command+list(args)+['--state-dir',str(state)],
                cwd=temp,env=env,capture_output=True,text=True,timeout=30)
            try:
                args=('start','--no-open','--port','0','--codex-home',str(codex))
                first=run(*args);self.assertEqual(first.returncode,0,first.stderr+first.stdout)
                info=json.loads((state/'service.json').read_text())
                second=run(*args);self.assertEqual(second.returncode,0,second.stderr)
                self.assertEqual(json.loads((state/'service.json').read_text())['instanceId'],info['instanceId'])
                result=run('status');self.assertEqual(result.returncode,0,result.stderr)
                self.assertFalse(json.loads(result.stdout)['bridge']['enabled'])
                self.assertTrue(json.loads(result.stdout)['bridge']['requested'])
                self.assertEqual(json.loads(result.stdout)['bridge']['connectionState'], 'waiting')
                import urllib.request
                with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/client.js") as response:
                    self.assertIn(b'CarryOnClient',response.read())
                self.assertEqual((state/'token').stat().st_mode&0o777,0o600)
                stopped=run('stop');self.assertEqual(stopped.returncode,0,stopped.stderr)
                self.assertEqual(run('status').returncode,1)
            finally:
                if (state/'service.json').exists():run('stop')

    def test_settings_commands_share_service_routes_and_binding_identity(self):
        cases=[(['bridge','on'],'/bridge',{'enabled':True}),
               (['bridge','off'],'/bridge',{'enabled':False}),
               (['standby','on'],'/service/standby',{'enabled':True}),
               (['standby','off'],'/service/standby',{'enabled':False}),
               (['cloud','control','--binding-id','binding-b','--read-only'],'/cloud/control',{'id':'binding-b','control':False}),
               (['cloud','control','--binding-id','binding-a','--allow-control'],'/cloud/control',{'id':'binding-a','control':True}),
               (['controller','set','--thread-id','thread-id'],'/controller',{'threadId':'thread-id'})]
        with tempfile.TemporaryDirectory() as temp:
            for arguments,path,body in cases:
                with self.subTest(arguments=arguments), patch('carryon.cli.running',return_value={'port':1234}), \
                        patch('carryon.cli.call',return_value={}) as call, redirect_stdout(io.StringIO()):
                    self.assertEqual(main(arguments+['--state-dir',temp]),0)
                    self.assertEqual(call.call_args.args,(Path(temp).resolve(),path,body))
            for arguments in [['cloud','control'],['controller','set']]:
                with patch('carryon.cli.running',return_value={'port':1234}), patch('carryon.cli.call') as call, redirect_stderr(io.StringIO()):
                    self.assertEqual(main(arguments+['--state-dir',temp]),1);call.assert_not_called()

    def test_settings_status_is_read_only(self):
        for arguments,path in [(['bridge','status'],'/status'),(['standby','status'],'/service/standby'),
                               (['controller','status'],'/status'),(['cloud','link-status'],'/cloud/link/status')]:
            with self.subTest(arguments=arguments), patch('carryon.cli.running',return_value={'port':1234}), \
                    patch('carryon.cli.call',return_value={}) as call, redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments),0)
                self.assertEqual(call.call_args.args[1:],(path,))

    def test_notification_change_preserves_other_preferences(self):
        prefs={'message':True,'done':False,'failed':True,'approval':True}
        with patch('carryon.cli.running',return_value={'port':1234}), \
                patch('carryon.cli.call',side_effect=[{'preferences':prefs},{}]) as call, redirect_stdout(io.StringIO()):
            self.assertEqual(main(['notifications','set','--no-message']),0)
            self.assertEqual(call.call_args.args[1:],('/notifications/preferences',{**prefs,'message':False}))
