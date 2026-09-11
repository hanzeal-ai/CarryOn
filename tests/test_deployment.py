import importlib.util
import io
from pathlib import Path
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('receiver',Path(__file__).resolve().parents[1]/'deployment/receive.py')
receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)

class DeploymentTests(unittest.TestCase):
    def wheel(self,*names,symlink=False):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as archive:
            for name in names:
                entry=zipfile.ZipInfo(name)
                if symlink:entry.external_attr=0o120777<<16
                archive.writestr(entry,'pass\n')
        return out.getvalue()
    def test_valid_gateway_wheel(self):
        archive=receiver.validate_wheel(self.wheel('connectnow/gateway.py','connectnow/__init__.py','connectnow_local-0.2.0.dist-info/METADATA'))
        self.assertIn('connectnow/gateway.py',archive.namelist())
    def test_unsafe_or_wrong_payload_refused_before_activation(self):
        for name in ['../outside','/etc/passwd','connectnow/../../outside','another_package/foo.py','connectnow\\escape.py']:
            with self.subTest(name=name),self.assertRaises(ValueError):
                receiver.validate_wheel(self.wheel('connectnow/gateway.py',name))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('connectnow/gateway.py',symlink=True))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('connectnow/__init__.py'))
        with self.assertRaises(ValueError):receiver.validate_wheel(self.wheel('connectnow/gateway.py','connectnow/gateway.py'))
