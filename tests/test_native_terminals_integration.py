"""Actual native background commands in a private home, driven by localhost model only."""
import io
import json
import os
import unittest
from unittest.mock import patch
import test_native_archives_integration as fixtures
from run_appserver_regression import Model, wait_until
from carryon.app_server.background_terminals import page
from carryon.desktop_ipc.ipc import IPCError


@unittest.skipUnless(os.environ.get('CARRYON_NATIVE_INTEGRATION') == '1', 'explicit isolated native integration')
class NativeTerminalsIntegration(unittest.TestCase):
    setUp = fixtures.NativeArchivesIntegration.setUp
    tearDown = fixtures.NativeArchivesIntegration.tearDown

    def background_turn(self, runtime, call_id='background-fixture'):
        original, phase = Model.do_POST, [0]
        def respond(handler):
            raw = handler.rfile.read(int(handler.headers.get('Content-Length', 0))); phase[0] += 1
            if phase[0] > 1:
                handler.rfile = io.BytesIO(raw); return original(handler)
            item = {'type': 'function_call', 'id': call_id, 'call_id': call_id, 'name': 'exec_command',
                    'arguments': json.dumps({'cmd': 'sleep 60', 'yield_time_ms': 1000, 'max_output_tokens': 100})}
            response = {'id': 'response-' + call_id, 'object': 'response', 'status': 'completed', 'output': [item],
                        'usage': {'input_tokens': 10, 'output_tokens': 3, 'total_tokens': 13}}
            events = [{'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': []}},
                      {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                      {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                      {'type': 'response.completed', 'response': response}]
            body = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode()
            handler.send_response(200); handler.send_header('Content-Type', 'text/event-stream'); handler.send_header('Content-Length', str(len(body))); handler.end_headers(); handler.wfile.write(body)
        with patch.object(Model, 'do_POST', respond):
            result = runtime.start_turn(self.tid, {'threadId': self.tid, 'approvalPolicy': 'never', 'input': [{'type': 'text', 'text': 'private background fixture only', 'text_elements': []}]})
            wait_until(lambda: runtime.current(self.tid)['turns'][-1]['status'] in ('completed', 'failed'))
            self.assertEqual(runtime.current(self.tid)['turns'][-1]['status'], 'completed')
            self.assertEqual(phase[0], 2)
            return result

    def test_owner_retains_live_terminal_and_refuses_archive_then_releases_after_termination(self):
        manager = fixtures.NativeArchivesIntegration.owner_fixture(self, False); runtime = self.runtime
        result = self.background_turn(runtime)
        manager._submitted(manager.entries[self.tid], 'thread-follower-start-turn', {'result': result})
        inventory, _ = page(runtime, self.tid)
        self.assertEqual(len(inventory['terminals']), 1); terminal = inventory['terminals'][0]
        self.assertEqual(terminal['command'], 'sleep 60')
        manager._release_finished(); self.assertTrue(runtime.connected)
        self.assertFalse(manager.entries[self.tid].get('suspended', False))
        self.assertEqual(fixtures.NativeArchivesIntegration.send(self, 'archive', 'background-archive')['state'], 'failed')
        self.assertTrue(runtime.connected)
        runtime.rpc('thread/backgroundTerminals/terminate', {'threadId': self.tid, 'processId': terminal['processId']})
        def empty_or_released():
            if not runtime.connected: return True
            try: return not page(runtime, self.tid)[0]['terminals']
            except IPCError: return not runtime.connected
        wait_until(empty_or_released)
        manager._release_finished(); wait_until(lambda: not runtime.connected)
        self.assertEqual(len(self.requests), len(self.baseline_requests) + 2)

    def test_direct_clean_only_native_terminals_and_unknown_pid_does_not_target_other_process(self):
        self.background_turn(self.runtime)
        self.background_turn(self.runtime, 'second-background-fixture')
        rows, _ = page(self.runtime, self.tid); ids = [row['processId'] for row in rows['terminals']]
        self.assertEqual(len(ids), 2); self.assertEqual(len(set(ids)), 2)
        with self.assertRaises(IPCError): self.runtime.rpc('thread/backgroundTerminals/terminate', {'threadId': self.tid, 'processId': 'not-a-native-process'})
        self.assertEqual({row['processId'] for row in page(self.runtime, self.tid)[0]['terminals']}, set(ids))
        self.runtime.rpc('thread/backgroundTerminals/clean', {'threadId': self.tid})
        wait_until(lambda: not page(self.runtime, self.tid)[0]['terminals'])
        self.assertEqual(len(self.requests), len(self.baseline_requests) + 4)

    def test_public_route_stop_confirms_original_native_id_without_replay_after_lost_reply(self):
        from carryon.app_server.app_server import AppServer
        from carryon.routes.api import dispatch
        from carryon.workspaces.workspace_access import required_capabilities
        self.background_turn(self.runtime)
        path = '/api/threads/' + self.tid + '/terminals'
        _, result = dispatch(self.bridge, 'GET', path)
        pid = result['terminals'][0]['processId']
        self.assertEqual(result['terminals'][0]['id'], pid)
        self.assertEqual(required_capabilities('GET', path), ('view',)); self.assertEqual(required_capabilities('POST', path), ('stop',))
        original, writes = AppServer.rpc, []
        def lost(runtime, method, params, *args, **kwargs):
            result = original(runtime, method, params, *args, **kwargs)
            if method == 'thread/backgroundTerminals/terminate': writes.append(params); raise IPCError('lost terminal reply', uncertain=True)
            return result
        body = {'requestId': 'unknown-terminal-stop', 'action': 'terminate', 'processId': pid}
        with patch.object(AppServer, 'rpc', lost):
            dispatch(self.bridge, 'POST', path, body)
            wait_until(lambda: self.journal.get(body['requestId'])['state'] == 'uncertain')
            self.assertEqual(dispatch(self.bridge, 'POST', path, body)[1]['state'], 'uncertain')
        original_session = self.runtime.session_id; self.runtime.session_id = 'replacement'
        self.assertEqual(self.bridge.refresh_job(body['requestId'])['state'], 'uncertain')
        self.runtime.session_id = original_session
        wait_until(lambda: self.bridge.refresh_job(body['requestId'])['state'] == 'completed')
        self.assertEqual(self.journal.get(body['requestId'])['result'], {'threadId': self.tid, 'processId': pid, 'terminated': True})
        self.assertEqual(len(writes), 1)
        self.assertEqual(len(self.requests), len(self.baseline_requests) + 2)

    def test_suspended_owner_terminal_read_does_not_allocate_or_resume_a_task(self):
        from carryon.routes.api import dispatch
        manager = fixtures.NativeArchivesIntegration.owner_fixture(self, True)
        snapshot = manager.entries[self.tid]['snapshot']
        with patch.object(manager.prewarm, 'take') as take:
            with self.assertRaises(IPCError): dispatch(self.bridge, 'GET', '/api/threads/' + self.tid + '/terminals')
            take.assert_not_called()
        self.assertIs(manager.entries[self.tid]['snapshot'], snapshot)
        self.assertTrue(manager.entries[self.tid]['suspended']); self.assertFalse(self.runtime.connected)
        self.assertEqual(self.requests, self.baseline_requests)

    def test_terminal_stop_and_archive_are_mutually_blocked_and_revocation_prevents_native_stop(self):
        from carryon.routes.api import dispatch
        path = '/api/threads/' + self.tid + '/terminals'
        for kind in ['archive', 'terminal-clean']:
            self.journal.insert({'id': 'pending-' + kind, 'kind': kind, 'threadId': self.tid, 'fingerprint': kind, 'state': 'uncertain', 'created': 0})
            with self.assertRaisesRegex(IPCError, '待核对'):
                if kind == 'archive': dispatch(self.bridge, 'POST', path, {'requestId': 'blocked-clean', 'action': 'clean'})
                else: dispatch(self.bridge, 'POST', '/api/threads/' + self.tid + '/archive', {'requestId': 'blocked-terminal-archive'})
            self.journal.update('pending-' + kind, state='failed')
        def denied(): raise PermissionError('revoked')
        with patch.object(self.runtime, 'rpc') as rpc:
            with self.assertRaises(PermissionError): dispatch(self.bridge, 'POST', path, {'requestId': 'denied-clean', 'action': 'clean'}, authorize=denied)
            rpc.assert_not_called()
        self.assertIsNone(self.journal.get('denied-clean')); self.assertEqual(self.requests, self.baseline_requests)
