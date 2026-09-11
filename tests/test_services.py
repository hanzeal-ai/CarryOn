import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from connectnow.services import register, records, list_services, process_directories

class ServiceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.env=patch.dict(os.environ,{'CONNECTNOW_REGISTRY_DIR':str(self.root/'registry')});self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_canonical_identity_and_concurrent_registration_keep_both_workspaces(self):
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda d:register(d,name=d.name,port=0,codex_home=self.root/'codex'),[a,b]))
        register(a/'..'/'a',port=8771)
        data=records();self.assertEqual(len(data),2)
        self.assertEqual(data[str(a)]['name'],'a');self.assertEqual(data[str(a)]['port'],8771)
        self.assertNotIn('running',json.dumps(data));self.assertNotIn('token',json.dumps(data))
        self.assertEqual((self.root/'registry/services.json').stat().st_mode&0o777,0o600)
    def test_legacy_process_is_only_online_after_service_authentication(self):
        a=self.root/'folder with spaces';a.mkdir()
        output=f'/some/ConnectNow serve --state-dir {a} --port 8771 --codex-home /codex\n/other/program serve --state-dir /not-connectnow --port 88\n'
        with patch('connectnow.services.subprocess.check_output',return_value=output):
            self.assertEqual(process_directories(),{str(a)})
        info={'port':8771,'codexHome':'/codex','instanceId':'one'}
        with patch('connectnow.services.process_directories',return_value={str(a)}),patch('connectnow.cli.running',side_effect=lambda d:info if d==a else None):
            rows=list_services(self.root/'default')['services']
        self.assertTrue(next(r for r in rows if r['directory']==str(a))['running'])
        self.assertIn(str(a),records())
        with patch('connectnow.services.process_directories',return_value=set()),patch('connectnow.cli.running',return_value=None):
            self.assertEqual(next(r for r in list_services(a)['services'] if r['directory']==str(a))['state'],'stopped')
            (a/'service.json').write_text('{}')
            self.assertEqual(next(r for r in list_services(a)['services'] if r['directory']==str(a))['state'],'unavailable')
    def test_invalid_catalog_is_not_overwritten(self):
        registry=self.root/'registry';registry.mkdir();p=registry/'services.json';p.write_text('{bad')
        with self.assertRaises(ValueError):register(self.root/'new')
        self.assertEqual(p.read_text(),'{bad')

    def test_import_running_directory_preserves_actual_startup_parameters(self):
        import io
        from contextlib import redirect_stdout
        from connectnow.cli import main
        active={'port':8779,'codexHome':str(self.root/'actual-codex')}
        with patch('connectnow.cli.running',return_value=active),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['services','add','--state-dir',str(self.root/'existing'),'--name','Existing','--port','0']),0)
        entry=records()[str(self.root/'existing')]
        self.assertEqual(entry['port'],8779)
        self.assertEqual(entry['codexHome'],active['codexHome'])
