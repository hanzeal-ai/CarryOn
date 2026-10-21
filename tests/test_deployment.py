import importlib.util
import io
from pathlib import Path
import unittest
import zipfile
import subprocess
import sys
import tempfile
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('receiver',Path(__file__).resolve().parents[1]/'deployment/receive.py')
receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)

class DeploymentTests(unittest.TestCase):
    def test_service_entrypoints_accept_documented_serve_command(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('carryon-gateway.service', 'console.service.conf'):
            text = (root / 'deployment' / name).read_text()
            command = next(line.removeprefix('ExecStart=') for line in text.splitlines()
                           if line.startswith('ExecStart=') and '-m ' in line).split()
            module = command[command.index('-m') + 1]
            result = subprocess.run([sys.executable, '-m', module, 'serve', '--help'],
                                    cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--config', result.stdout)

    def wheel(self,*names,symlink=False):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as archive:
            for name in names:
                entry=zipfile.ZipInfo(name)
                if symlink:entry.external_attr=0o120777<<16
                archive.writestr(entry,'pass\n')
        return out.getvalue()
    def test_valid_gateway_wheel(self):
        archive=receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py','carryon/__init__.py','carryon_local-0.2.0.dist-info/METADATA'))
        self.assertIn('carryon/cloud/gateway.py',archive.namelist())
    def test_effective_service_entrypoint_must_exist_in_wheel(self):
        with receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py','carryon/cloud/console.py')) as archive:
            for module in ('carryon.cloud.gateway','carryon.cloud.console'):
                output='{ path=/usr/bin/python3.11 ; argv[]=/usr/bin/python3.11 -m '+module+' serve --config /etc/carryon/gateway.json ; }'
                with self.subTest(module=module),patch.object(receiver.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout=output)):
                    self.assertEqual(receiver.service_module(archive),module)
            for module in ('carryon.gateway','carryon.console'):
                output='{ argv[]=/usr/bin/python3.11 -m '+module+' serve ; }'
                with self.subTest(module=module),patch.object(receiver.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout=output)):
                    with self.assertRaisesRegex(ValueError,'operator must update'):
                        receiver.service_module(archive)
    def test_unrecognized_service_command_is_refused(self):
        with receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py')) as archive:
            with patch.object(receiver.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='{ argv[]=/bin/sh wrapper.sh ; }')):
                with self.assertRaisesRegex(ValueError,'Cannot identify'):
                    receiver.service_module(archive)
    def test_old_service_entrypoint_is_refused_before_release_mutation(self):
        wheel=self.wheel('carryon/cloud/gateway.py')
        fake_input=io.TextIOWrapper(io.BytesIO(wheel))
        with patch.dict(receiver.os.environ,{'SSH_ORIGINAL_COMMAND':'a'*40}),patch.object(receiver.sys,'stdin',fake_input):
            with patch.object(receiver.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='{ argv[]=/usr/bin/python3.11 -m carryon.console serve ; }')):
                with patch.object(receiver.Path,'open') as open_file,patch.object(receiver,'switch') as switch,patch.object(receiver,'systemctl') as systemctl:
                    with self.assertRaisesRegex(ValueError,'carryon.console'):
                        receiver.main()
                    open_file.assert_not_called()
                    switch.assert_not_called()
                    systemctl.assert_not_called()
    def test_wheel_check_refuses_missing_console_without_source_fallback(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            wheel=Path(directory)/'missing-console.whl'
            with zipfile.ZipFile(wheel,'w') as archive:
                archive.writestr('carryon/__init__.py','')
                archive.writestr('carryon/cloud/__init__.py','')
                archive.writestr('carryon/cloud/gateway.py',"print('--config')\n")
            result=subprocess.run(
                [sys.executable,'-B',str(root/'deployment/check_wheel.py'),str(wheel)],
                cwd=root,capture_output=True,text=True,timeout=20)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Wheel entrypoint check failed for carryon.cloud.console',result.stderr)
    def test_unsafe_or_wrong_payload_refused_before_activation(self):
        for name in ['../outside','/etc/passwd','carryon/../../outside','another_package/foo.py','carryon\\escape.py']:
            with self.subTest(name=name),self.assertRaises(ValueError):
                receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py',name))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py',symlink=True))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('carryon/__init__.py'))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py','carryon/cloud/gateway.py'))
