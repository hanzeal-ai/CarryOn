import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.request
import urllib.error

from carryon.standby import RemoteStandby
from carryon.api import dispatch
from carryon.errors import BridgeError
from carryon.server import Server, Handler


class StandbyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.standby = RemoteStandby(self.temp.name)
        self.process = Mock()
        self.process.poll.return_value = None
        self.patches = [patch('carryon.standby.Path.is_file',return_value=True), patch('carryon.standby.sys.platform', 'darwin'),
                        patch('carryon.standby.subprocess.Popen', return_value=self.process),
                        patch.object(RemoteStandby, 'power_source', return_value='ac')]
        for p in self.patches:p.start()

    def tearDown(self):
        self.standby.close()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_opt_in_ac_only_service_scoped_and_release(self):
        self.standby.start()
        self.assertIsNone(self.standby.process)
        result=self.standby.configure(True)
        self.assertTrue(result['effective'])
        from carryon.standby import subprocess
        self.assertEqual(subprocess.Popen.call_args.args[0], ['/usr/bin/caffeinate','-s','-w',str(os.getpid())])
        self.assertEqual(self.standby.path.stat().st_mode & 0o777,0o600)
        with patch.object(RemoteStandby,'power_source',return_value='battery'):
            self.assertFalse(self.standby.status()['effective'])
        self.standby.configure(True)
        self.assertEqual(subprocess.Popen.call_count,1)
        self.standby.configure(False)
        self.process.terminate.assert_called_once()
        self.assertFalse(self.standby.status()['running'])
        self.assertFalse(RemoteStandby(self.temp.name).enabled)

    def test_saved_opt_in_restored_but_close_keeps_preference(self):
        self.standby.configure(True)
        self.standby.close()
        restored=RemoteStandby(self.temp.name)
        self.assertTrue(restored.enabled)
        restored.start();self.assertTrue(restored.status()['running']);restored.close()

    def test_invalid_unsupported_failed_process_and_save_failure(self):
        for value in (1, 'true', None):
            with self.assertRaises(ValueError):self.standby.configure(value)
        with patch('carryon.standby.sys.platform','linux'):
            with self.assertRaises(ValueError):self.standby.configure(True)
        with patch('carryon.standby.subprocess.Popen',side_effect=OSError):
            with self.assertRaises(ValueError):self.standby.configure(True)
        self.assertFalse(self.standby.enabled)
        with patch('carryon.standby.save_json',side_effect=OSError):
            with self.assertRaises(OSError):self.standby.configure(True)
        self.assertFalse(self.standby.enabled);self.assertIsNone(self.standby.process)
        self.standby.configure(True);self.process.poll.return_value=1
        self.assertFalse(self.standby.status()['effective'])
        self.assertIsNotNone(self.standby.status()['error'])

    def test_remote_cannot_read_or_change_local_standby(self):
        for method in ('GET','POST'):
            with self.assertRaises(BridgeError) as e:
                dispatch(Mock(),method,'/api/service/standby',{'enabled':True},remote=True,control=True)
            self.assertEqual(e.exception.status,403)

    def test_local_http_requires_authentication(self):
        server=Server(('127.0.0.1',0),Handler)
        server.token='standby-test-token';server.bridge=Mock();server.standby=self.standby
        address=f'127.0.0.1:{server.server_port}';server.allowed_hosts={address}
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://{address}/api/service/standby'
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(url)
            self.assertEqual(e.exception.code,401);e.exception.close()
            headers={'Authorization':'Bearer '+server.token,'Content-Type':'application/json'}
            req=urllib.request.Request(url,headers=headers,data=b'{"enabled":true}')
            with urllib.request.urlopen(req) as response:self.assertTrue(json.load(response)['effective'])
        finally:server.shutdown();server.server_close();thread.join()
