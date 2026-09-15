import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from carryon.api import dispatch
from carryon.errors import BridgeError
from carryon.usage import native_read, project


class UsageTests(unittest.TestCase):
    def test_multi_bucket_preferred_and_unknown_is_not_zero(self):
        raw = {'rateLimits': {'primary': {'usedPercent': 90}}, 'rateLimitsByLimitId': {
            'codex': {'limitName': 'Codex', 'primary': {'usedPercent': 23, 'windowDurationMins': 300, 'resetsAt': 2000000000}, 'accountId': 'private'},
            'other': {'secondary': {'usedPercent': None, 'windowDurationMins': 10080}},
        }, 'token': 'private'}
        result = project(raw)
        self.assertEqual(result['limits'][0]['windows'][0]['usedPercent'], 23)
        self.assertIsNone(result['limits'][1]['windows'][0]['usedPercent'])
        self.assertNotIn('private', json.dumps(result))

    def test_legacy_null_invalid_and_clamping(self):
        self.assertEqual(project({'rateLimits': None})['limits'], [])
        result = project({'rateLimits': {'primary': {'usedPercent': 105}, 'secondary': {'usedPercent': True, 'resetsAt': -1}}})
        self.assertEqual(result['limits'][0]['windows'][0]['usedPercent'], 100)
        self.assertIsNone(result['limits'][0]['windows'][1]['usedPercent'])
        self.assertIsNone(result['limits'][0]['windows'][1]['resetsAt'])
        with self.assertRaises(BridgeError): project([])

    def test_route_is_read_only_and_uses_selected_bridge_home(self):
        home = Path('/workspace-selected/codex')
        bridge = SimpleNamespace(catalog=SimpleNamespace(home=home), require=lambda: None)
        with patch('carryon.usage.read', return_value={'limits': []}) as reader:
            self.assertEqual(dispatch(bridge, 'GET', '/api/usage', remote=True, control=False), (200, {'limits': []}))
            reader.assert_called_once_with(home)
            with self.assertRaises(BridgeError): dispatch(bridge, 'POST', '/api/usage', remote=True, control=False)
            self.assertEqual(reader.call_count, 1)
        denied = SimpleNamespace(require=lambda: (_ for _ in ()).throw(BridgeError('disabled', 403)))
        with patch('carryon.usage.read') as reader:
            with self.assertRaises(BridgeError): dispatch(denied, 'GET', '/api/usage')
            reader.assert_not_called()

    def test_native_protocol_home_and_child_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            stub = home / 'codex'
            stub.write_text('''#!/usr/bin/env python3
import sys,json,os
methods=[]
for line in sys.stdin:
    request=json.loads(line); methods.append(request['method'])
    if 'id' not in request: continue
    result={}
    if request['method']=='account/read': result={'account':{'type':'chatgpt'}}
    if request['method']=='account/rateLimits/read': result={'home':os.environ['CODEX_HOME'],'cwd':os.getcwd(),'methods':methods,'pid':os.getpid()}
    print(json.dumps({'id':request['id'],'result':result}),flush=True)
''')
            stub.chmod(0o700)
            with patch('carryon.usage.executable', return_value=str(stub)):
                result = native_read(home)
            self.assertEqual(result['home'], str(home.resolve()))
            self.assertEqual(result['cwd'], str(home.resolve()))
            self.assertEqual(result['methods'], ['initialize', 'initialized', 'account/read', 'account/rateLimits/read'])
            with self.assertRaises(ProcessLookupError): os.kill(result['pid'], 0)

    def test_capacity_limit_fails_without_starting_another_child(self):
        from carryon.usage import _slots
        _slots.acquire(); _slots.acquire()
        try:
            with patch('carryon.usage._native_read') as reader:
                with self.assertRaises(BridgeError): native_read('/unused')
                reader.assert_not_called()
        finally:
            _slots.release(); _slots.release()

    def test_cleanup_still_kills_after_pipe_close_and_terminate_errors(self):
        import subprocess
        from unittest.mock import MagicMock
        process = MagicMock()
        process.stdin.close.side_effect = BrokenPipeError()
        process.terminate.side_effect = ProcessLookupError()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('codex', 2), 0]
        selector = MagicMock()
        selector.register.side_effect = OSError('registration failed')
        with patch('carryon.usage.executable', return_value='/unused'), patch('carryon.usage.subprocess.Popen', return_value=process), patch('carryon.usage.selectors.DefaultSelector', return_value=selector):
            with self.assertRaises(OSError): native_read('/tmp')
        process.kill.assert_called_once()
        process.stdout.close.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_selector_creation_failure_still_reaps_child(self):
        from unittest.mock import MagicMock
        process = MagicMock()
        process.poll.return_value = None
        with patch('carryon.usage.executable', return_value='/unused'), patch('carryon.usage.subprocess.Popen', return_value=process), patch('carryon.usage.selectors.DefaultSelector', side_effect=OSError('no descriptors')):
            with self.assertRaises(OSError): native_read('/tmp')
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=2)
        process.stdin.close.assert_called_once()
        process.stdout.close.assert_called_once()
