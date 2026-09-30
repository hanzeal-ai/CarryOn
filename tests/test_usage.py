import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from carryon.routes.api import dispatch
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

    def test_missing_map_invalid_and_clamping(self):
        self.assertEqual(project({'rateLimits': {'primary': {'usedPercent': 90}}})['limits'], [])
        result = project({'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 105}, 'secondary': {'usedPercent': True, 'resetsAt': -1}}}})
        self.assertEqual(result['limits'][0]['windows'][0]['usedPercent'], 100)
        self.assertIsNone(result['limits'][0]['windows'][1]['usedPercent'])
        self.assertIsNone(result['limits'][0]['windows'][1]['resetsAt'])
        with self.assertRaises(BridgeError): project([])

    def test_reset_credit_count_is_native_not_detail_length(self):
        result = project({'rateLimitResetCredits': {'availableCount': 5, 'credits': [
            {'id': 'card', 'title': 'Quota reset', 'status': 'available',
             'grantedAt': 1800000000, 'expiresAt': 1900000000, 'secret': 'private'}]}, 'token': 'private'})
        summary = result['rateLimitResetCredits']
        self.assertEqual(summary['availableCount'], 5)
        self.assertEqual(len(summary['credits']), 1)
        self.assertEqual(summary['credits'][0]['expiresAt'], 1900000000)
        self.assertEqual(summary['credits'][0]['grantedAt'], 1800000000)
        self.assertNotIn('private', json.dumps(result))

    def test_reset_credit_unknown_zero_and_partial_details(self):
        self.assertIsNone(project({})['rateLimitResetCredits'])
        for details in (None, []):
            summary = project({'rateLimitResetCredits': {'availableCount': 0, 'credits': details}})['rateLimitResetCredits']
            self.assertEqual(summary, {'availableCount': 0, 'credits': details})
        summary = project({'rateLimitResetCredits': {'availableCount': 3}})['rateLimitResetCredits']
        self.assertEqual(summary, {'availableCount': 3, 'credits': None})
        for count in (True, -1, 1.5, '2'):
            summary = project({'rateLimitResetCredits': {'availableCount': count, 'credits': [None,
                {'id': 'card', 'status': 'unexpected', 'grantedAt': True, 'expiresAt': -2}]}})['rateLimitResetCredits']
            self.assertIsNone(summary['availableCount'])
            self.assertEqual(summary['credits'], [{'id': 'card', 'title': None, 'status': 'unknown', 'grantedAt': None, 'expiresAt': None}])

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
