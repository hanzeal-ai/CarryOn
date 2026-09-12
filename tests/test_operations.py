import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path

from carryon.bridge import Bridge, BridgeError
from carryon.ipc import IPCError
from carryon.operations import METHODS, REQUEST_METHODS, build, controls, digest, submit
from carryon.store import Journal

T = '11111111-1111-4111-8111-111111111111'


def state(runtime='idle'):
    return {'id': T, 'cwd': '/tmp', 'threadRuntimeStatus': {'type': runtime}, 'requests': [],
            'turns': [{'turnId': 'turn-1', 'status': 'inProgress' if runtime == 'active' else 'completed',
                       'params': {'input': [{'type': 'text', 'text': 'original'}]}}]}


class ContractTests(unittest.TestCase):
    def test_stale_turn_cannot_interrupt_or_steer(self):
        for action in ('interrupt', 'steer'):
            with self.assertRaises(ValueError):
                build(action, {'expectedTurnId': 'old', 'prompt': 'hello'}, state('active'))
            method, version, p = build(action, {'expectedTurnId': 'turn-1', 'prompt': 'hello'}, state('active'))
            self.assertTrue(method.startswith('thread-follower-'))
            if action == 'interrupt':
                self.assertEqual((version, p['expectedTurnId'], p['mode']), (4, 'turn-1', 'user-stop'))
            else:
                self.assertEqual(p['restoreMessage']['context']['prompt'], 'hello')

    def test_idle_operations_reject_active_or_pending(self):
        for action in ('compact', 'edit'):
            with self.assertRaises(ValueError): build(action, {}, state('active'))
            s = state(); s['requests'] = [{'id': 1, 'method': 'unknown'}]
            with self.assertRaises(ValueError): build(action, {}, s)
            for flag in ('waitingOnApproval', 'waitingOnUserInput'):
                s = state(); s['threadRuntimeStatus']['activeFlags'] = [flag]
                with self.assertRaises(ValueError):
                    build(action, {'turnId':'turn-1','prompt':'new','confirmed':True}, s)

    def test_edit_requires_current_last_turn_and_confirmation(self):
        for data in ({'turnId': 'old', 'confirmed': True}, {'turnId': 'turn-1'}):
            with self.assertRaises(ValueError): build('edit', {**data, 'prompt': 'new'}, state())
        _, version, p = build('edit', {'turnId': 'turn-1', 'prompt': 'new', 'confirmed': True}, state())
        self.assertEqual(version, 2); self.assertFalse(p['shouldSendPermissionOverrides'])

    def test_settings_validate_native_fields_and_reject_unknown_parameters(self):
        for value in ({'unknownField': True}, {'model': []}, {'effort': ''}, {'sandboxPolicy': {'type':'evil'}}):
            with self.assertRaises(ValueError): build('settings', {'settings': value}, state())
        self.assertEqual(build('settings', {'settings': {'model': 'm', 'effort': 'high'}}, state())[2]['threadSettings']['model'], 'm')

    def test_clear_queue_is_explicit_and_scoped(self):
        with self.assertRaises(ValueError): build('clear-queue', {}, {**state(), 'nativeQueue': []})
        self.assertEqual(build('clear-queue', {'confirmed': True, 'queueFingerprint':digest([]), 'state': {'other': []}}, {**state(), 'nativeQueue':[]})[2]['state'], {T: []})

    def request(self, action, params=None):
        s = state('active'); r = {'id': 7, 'method': REQUEST_METHODS[action], 'params': params or {}}
        s['requests'] = [r]
        return s, {'nativeRequestId': 7, 'requestFingerprint': digest(r)}

    def test_request_identity_type_content_and_method_are_bound(self):
        s, data = self.request('command-approval')
        for changed in ({'nativeRequestId': '7'}, {'requestFingerprint': 'old'}):
            with self.assertRaises(ValueError): build('command-approval', {**data, **changed, 'decision': 'accept'}, s)
        with self.assertRaises(ValueError): build('file-approval', {**data, 'decision': 'accept'}, s)
        s['requests'][0]['params']['command'] = 'changed'
        with self.assertRaises(ValueError): build('command-approval', {**data, 'decision': 'accept'}, s)

    def test_approval_is_once_and_respects_available_decisions(self):
        s, data = self.request('command-approval', {'availableDecisions': ['decline']})
        for decision in ('accept', 'acceptForSession'):
            with self.assertRaises(ValueError): build('command-approval', {**data, 'decision': decision}, s)
        self.assertEqual(build('command-approval', {**data, 'decision': 'decline'}, s)[2]['decision'], 'decline')

    def test_permissions_come_only_from_native_request(self):
        perms = {'fileSystem': {'read': ['/tmp/test']}}
        s, data = self.request('permissions-approval', {'permissions': perms})
        p = build('permissions-approval', {**data, 'decision': 'accept', 'permissions': {'all': True}}, s)[2]
        self.assertEqual(p['response'], {'scope': 'turn', 'permissions': perms})

    def test_user_input_schema_and_question_binding(self):
        s, data = self.request('user-input', {'questions': [{'id': 'q'}]})
        for answers in ({'other': ['hi']}, {'q': 'hi'}, {'q': []}):
            with self.assertRaises(ValueError): build('user-input', {**data, 'answers': answers}, s)
        self.assertEqual(build('user-input', {**data, 'answers': {'q': ['hi']}}, s)[2]['response'], {'answers': {'q': {'answers': ['hi']}}})

    def test_all_response_methods_and_mcp_envelope(self):
        for action in REQUEST_METHODS:
            s, data = self.request(action)
            data.update(decision='decline', answers={}, response={'action': 'decline'})
            if action == 'permissions-approval':
                data['response'] = {'permissions': {}, 'scope': 'turn'}
            self.assertEqual(build(action, data, s)[0], 'thread-follower-' + METHODS[action][0])
        s, data = self.request('mcp-response')
        with self.assertRaises(ValueError): build('mcp-response', {**data, 'response': {'action': 'evil'}}, s)


class IPC:
    def __init__(self, _): self.connected = False; self.calls = []; self.error = None; self.state = state()
    def connect(self): self.connected = True
    def close(self): self.connected = False
    def snapshot(self, _): return 'owner', copy.deepcopy(self.state)
    def current(self, _): return self.state
    def request(self, method, params, version, owner, guard):
        guard(lambda: self.calls.append((method, params, version, owner)))
        if self.error: raise self.error
        return {'result': {'ok': True}}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.temp.name) / 'jobs.sqlite')
        class Catalog:
            def get(self, _): return {}
        self.bridge = Bridge('socket', Catalog(), self.journal, IPC); self.bridge.enable()
    def tearDown(self):
        self.bridge.disable(); self.journal.conn.close(); self.temp.cleanup()
    def wait(self, rid='operation-1'):
        for _ in range(100):
            j = self.journal.get(rid)
            if j['state'] not in ('preparing', 'dispatching'): return j
            time.sleep(.01)
        self.fail('operation stuck')
    def test_duplicate_never_resends_and_conflict_rejected(self):
        d = {'action': 'compact', 'requestId': 'operation-1'}
        submit(self.bridge, T, d); self.assertEqual(self.wait()['state'], 'completed')
        submit(self.bridge, T, d); self.assertEqual(len(self.bridge.ipc.calls), 1)
        with self.assertRaises(BridgeError): submit(self.bridge, T, {**d, 'action': 'clear-queue'})
    def test_uncertain_blocks_replay_and_followup(self):
        self.bridge.ipc.error = IPCError('timeout', uncertain=True)
        d = {'action': 'compact', 'requestId': 'operation-1'}
        submit(self.bridge, T, d); self.assertEqual(self.wait()['state'], 'uncertain')
        submit(self.bridge, T, d)
        with self.assertRaises(BridgeError): submit(self.bridge, T, {**d, 'requestId': 'operation-2'})
        self.assertEqual(len(self.bridge.ipc.calls), 1)
    def test_disable_during_snapshot_prevents_write(self):
        ready, resume = threading.Event(), threading.Event()
        ipc = self.bridge.ipc
        def snapshot(_): ready.set(); resume.wait(2); return 'owner', state()
        ipc.snapshot = snapshot
        submit(self.bridge, T, {'action': 'compact', 'requestId': 'operation-1'})
        self.assertTrue(ready.wait(1)); self.bridge.disable(); resume.set()
        self.assertEqual(self.wait()['state'], 'failed'); self.assertEqual(ipc.calls, [])
    def test_native_failure_is_not_success(self):
        self.bridge.ipc.error = IPCError('no-handler-for-request')
        submit(self.bridge, T, {'action': 'compact', 'requestId': 'operation-1'})
        self.assertEqual(self.wait()['state'], 'failed')


if __name__ == '__main__': unittest.main()
