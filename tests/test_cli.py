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
                               (['controller','status'],'/status')]:
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
