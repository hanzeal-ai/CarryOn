import importlib.util
import io
from pathlib import Path
import unittest
import zipfile
import subprocess
import sys

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
    def test_unsafe_or_wrong_payload_refused_before_activation(self):
        for name in ['../outside','/etc/passwd','carryon/../../outside','another_package/foo.py','carryon\\escape.py']:
            with self.subTest(name=name),self.assertRaises(ValueError):
                receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py',name))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py',symlink=True))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('carryon/__init__.py'))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('carryon/cloud/gateway.py','carryon/cloud/gateway.py'))
