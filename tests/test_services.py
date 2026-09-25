import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from carryon.services import register, records, list_services, remove

class ServiceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.env=patch.dict(os.environ,{'CARRYON_REGISTRY_DIR':str(self.root/'registry')});self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_canonical_identity_and_concurrent_registration_keep_both_workspaces(self):
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda d:register(d,name=d.name,port=0,codex_home=d/'codex-home'),[a,b]))
        register(a/'..'/'a',port=8771)
        data=records();self.assertEqual(len(data),2)
        self.assertEqual(data[str(a)]['name'],'a');self.assertEqual(data[str(a)]['port'],8771)
        self.assertNotIn('running',json.dumps(data));self.assertNotIn('token',json.dumps(data))
        self.assertEqual((self.root/'registry/services.json').stat().st_mode&0o777,0o600)
    def test_current_directory_is_only_online_after_service_authentication(self):
        a=self.root/'folder with spaces';a.mkdir()
        info={'port':8771,'codexHome':'/codex','instanceId':'one'}
        with patch('carryon.services.running',side_effect=lambda d:info if d==a else None):
            rows=list_services(a)['services']
        self.assertTrue(next(r for r in rows if r['directory']==str(a))['running'])
        self.assertIn(str(a),records())
        with patch('carryon.services.running',return_value=None):
            self.assertEqual(next(r for r in list_services(a)['services'] if r['directory']==str(a))['state'],'stopped')
            (a/'service.json').write_text('{}')
            self.assertEqual(next(r for r in list_services(a)['services'] if r['directory']==str(a))['state'],'unavailable')
    def test_invalid_catalog_is_not_overwritten(self):
        registry=self.root/'registry';registry.mkdir();p=registry/'services.json';p.write_text('{bad')
        with self.assertRaises(ValueError):register(self.root/'new')
        self.assertEqual(p.read_text(),'{bad')

    def test_discovered_running_directory_preserves_actual_startup_parameters(self):
        active={'port':8779,'codexHome':str(self.root/'actual-codex')}
        existing=str(self.root/'existing')
        with patch('carryon.services.running',side_effect=lambda d: active if str(d) == existing else None):
            list_services(existing)
        self.assertEqual(set(records()), {existing})
        entry=records()[existing]
        self.assertEqual(entry['port'],8779)
        self.assertEqual(entry['codexHome'],active['codexHome'])

    def test_remove_preserves_files_and_other_entries_and_can_be_readded(self):
        a=self.root/'a';a.mkdir();(a/'keep').write_text('configuration')
        b=self.root/'b';register(a,name='A');register(b,name='B')
        with patch('carryon.services.running',return_value=None):
            remove(a)
            self.assertNotIn(str(a),[row['directory'] for row in list_services(a)['services']])
            self.assertEqual((a/'keep').read_text(),'configuration')
            self.assertFalse(records()[str(b)].get('removed'))
            register(a)
            self.assertEqual(next(row for row in list_services(a)['services'] if row['directory']==str(a))['name'],'A')

    def test_remove_running_service_is_refused_without_catalog_change(self):
        a=self.root/'a';register(a)
        before=records()
        with patch('carryon.services.running',return_value={'instanceId':'active'}):
            with self.assertRaisesRegex(ValueError,'先停止'):remove(a)
        self.assertEqual(records(),before)

    def test_last_default_workspace_stays_removed(self):
        directory=self.root/'default'
        with patch('carryon.services.state_dir',return_value=directory),  patch('carryon.services.running',return_value=None):
            self.assertEqual(len(list_services()['services']),1)
            remove(directory)
            self.assertEqual(list_services()['services'],[])
            register(directory,name='Restored')
            self.assertEqual(len(list_services()['services']),1)

class CleanupTests(unittest.TestCase):
    def test_cleanup_continues_after_cloud_stop_failure(self):
        from unittest.mock import Mock
        from carryon.server import close_resources
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            server, bridge, lock, ipc_lock = Mock(), Mock(), Mock(), Mock()
            bridge.realtime = None
            server.service_info = {'instanceId': 'test'}
            (directory / 'service.json').write_text('{"instanceId":"test"}')
            server.cloud.stop.side_effect = ValueError('cloud thread blocked')
            with self.assertRaisesRegex(ValueError, 'cloud thread blocked'):
                close_resources(server, bridge, directory, lock, ipc_lock)
            bridge.disable.assert_called_once()
            server.server_close.assert_called_once()
            lock.close.assert_called_once()
            ipc_lock.close.assert_called_once()
            self.assertFalse((directory / 'service.json').exists())
