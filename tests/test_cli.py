import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

class CLITests(unittest.TestCase):
    def test_start_reuse_assets_and_authenticated_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state';codex=Path(temp)/'empty-codex';codex.mkdir()
            env=dict(os.environ)
            binary=os.environ.get('CONNECTNOW_TEST_EXECUTABLE')
            if binary:env.pop('PYTHONPATH',None)
            else:env['PYTHONPATH']=str(ROOT)
            command=[binary] if binary else [sys.executable,'-m','connectnow']
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
                import urllib.request
                with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/client.js") as response:
                    self.assertIn(b'ConnectNowClient',response.read())
                self.assertEqual((state/'token').stat().st_mode&0o777,0o600)
                stopped=run('stop');self.assertEqual(stopped.returncode,0,stopped.stderr)
                self.assertEqual(run('status').returncode,1)
            finally:
                if (state/'service.json').exists():run('stop')
