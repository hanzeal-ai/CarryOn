import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from carryon.app_server.app_server import AppServer
from carryon.errors import IPCError
from carryon.sessions.bridge import Bridge
from carryon.sessions.operations import submit
from carryon.store import Journal

T = '11111111-1111-4111-8111-111111111111'


class NativeEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name) / 'jobs.sqlite'); self.addCleanup(self.journal.conn.close)
        self.runtime = AppServer(self.temp.name)
        self.runtime.process = SimpleNamespace(poll=lambda: None)
        self.runtime.account_ready = True
        self.turns = [{'id': name, 'status': 'completed', 'items': [{'type': 'userMessage', 'id': name + '-user',
            'content': [{'type': 'text', 'text': name, 'text_elements': []}]}]} for name in ('first', 'last')]
        self.runtime._event({'method': 'thread/started', 'params': {'thread': {'id': T, 'cwd': self.temp.name,
            'status': {'type': 'idle'}, 'turns': copy.deepcopy(self.turns)}}})
        self.runtime.current(T)['threadMetadata'] = {'id': T, 'cwd': self.temp.name, 'historyMode': 'paginated'}
        self.bridge = Bridge('unused', SimpleNamespace(get=lambda tid: {}), self.journal)
        self.bridge.enabled = True; self.bridge.ipc = self.runtime
        self.calls = []; self.errors = {}; self.queue = []; self.after_revert = lambda: None
        self.runtime.rpc = self.rpc
        self.data = {'action': 'edit', 'requestId': 'edit-request', 'turnId': 'last', 'prompt': 'replacement', 'confirmed': True}

    def rpc(self, method, params, before_send=None, **kwargs):
        if method == 'thread/goal/get': return {'goal': None}
        if method == 'thread/queue/list': return {'data': self.queue}
        if method == 'thread/resume':
            return {'thread': {'id': T, 'cwd': self.temp.name, 'historyMode': 'paginated',
                               'status': self.runtime.current(T)['threadRuntimeStatus']}}
        if method == 'thread/turns/list':
            if method in self.errors: raise self.errors[method]
            return {'data': copy.deepcopy(self.turns), 'nextCursor': None}
        def write(): self.calls.append((method, params))
        if before_send: before_send(write)
        else: write()
        if method in self.errors: raise self.errors[method]
        if method == 'thread/revert':
            self.turns = self.turns[:-1]; self.after_revert()
            return {'thread': {'id': T, 'cwd': self.temp.name, 'historyMode': 'paginated', 'status': {'type': 'idle'}, 'turns': []}}
        if method == 'turn/start':
            return {'turn': {'id': 'replacement-turn', 'status': 'inProgress', 'items': []}}
        raise AssertionError(method)

    def edit(self, authorize=None): return submit(self.bridge, T, self.data, authorize=authorize)

    def test_success_retains_history_and_attachment_and_deduplicates(self):
        self.runtime.current(T)['turns'][-1]['items'][0]['content'].append({'type': 'image', 'url': 'fixture:image'})
        job = self.edit()
        self.assertEqual(job['state'], 'completed', job)
        self.assertEqual([m for m, _ in self.calls], ['thread/revert', 'turn/start'])
        self.assertEqual([t['turnId'] for t in self.runtime.current(T)['turns']], ['first', 'replacement-turn'])
        self.assertEqual(self.calls[-1][1]['input'][-1], {'type': 'image', 'url': 'fixture:image'})
        self.assertEqual(self.calls[-1][1]['clientUserMessageId'], job['clientMessageId'])
        self.assertEqual(self.edit(), job)
        self.assertEqual(len(self.calls), 2)

    def test_structured_skill_survives_edit_and_is_revalidated_before_revert(self):
        skill = {'type': 'skill', 'name': 'fixture', 'path': self.temp.name + '/SKILL.md'}
        self.runtime.current(T)['turns'][-1]['items'][0]['content'].append(skill)
        original = self.rpc
        enabled = [False]
        def rpc(method, params, before_send=None, **kwargs):
            if method == 'skills/list':
                return {'data': [{'cwd': self.temp.name, 'skills': [{'name': skill['name'], 'path': skill['path'], 'enabled': enabled[0]}], 'errors': []}]}
            return original(method, params, before_send, **kwargs)
        self.runtime.rpc = rpc
        job = submit(self.bridge, T, self.data)
        self.assertEqual(job['state'], 'failed'); self.assertEqual(self.calls, [])
        enabled[0] = True
        self.data['requestId'] = 'enabled-skill-edit'
        job = submit(self.bridge, T, self.data)
        self.assertEqual(job['state'], 'completed', job)
        self.assertIn(skill, self.calls[-1][1]['input'])

    def test_revert_unknown_never_starts_or_replays(self):
        self.errors['thread/revert'] = IPCError('lost revert', uncertain=True)
        job = self.edit()
        self.assertEqual((job['state'], job['editPhase']), ('uncertain', 'reverting'))
        self.assertEqual([m for m, _ in self.calls], ['thread/revert'])
        self.assertEqual(self.edit(), job)
        self.assertEqual(len(self.calls), 1)

    def test_authority_revoked_after_revert_reports_partial_without_start(self):
        allowed = [True]
        self.after_revert = lambda: allowed.__setitem__(0, False)
        def authorize():
            if not allowed[0]: raise PermissionError('revoked')
        job = self.edit(authorize)
        self.assertEqual((job['state'], job['editPhase']), ('failed', 'reverted'))
        self.assertIn('已回退', job['error'])
        self.assertEqual([m for m, _ in self.calls], ['thread/revert'])

    def test_generation_change_after_revert_never_starts(self):
        self.after_revert = lambda: setattr(self.bridge, 'generation', self.bridge.generation + 1)
        job = self.edit()
        self.assertEqual(job['state'], 'failed')
        self.assertIn('已回退', job['error'])
        self.assertEqual(len(self.calls), 1)

    def test_history_refresh_failure_invalidates_snapshot_and_reports_partial(self):
        self.errors['thread/turns/list'] = IPCError('read failed')
        job = self.edit()
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['revertedTurnId'], 'last')
        self.assertEqual(self.runtime.current(T)['threadRuntimeStatus']['type'], 'notLoaded')
        self.assertEqual(len(self.calls), 1)

    def test_start_unknown_has_exact_recovery_identity(self):
        self.errors['turn/start'] = IPCError('lost start', uncertain=True)
        job = self.edit()
        self.assertEqual((job['state'], job['editPhase']), ('uncertain', 'starting'))
        self.assertEqual(job['clientMessageId'], self.calls[-1][1]['clientUserMessageId'])
        self.runtime._event({'method': 'turn/started', 'params': {'threadId': T, 'turn': {
            'id': 'recovered', 'status': 'inProgress', 'items': [{'type': 'userMessage',
            'id': 'native-id', 'clientId': job['clientMessageId'], 'content': [{'type': 'text', 'text': 'replacement'}]}]}}})
        self.turns = copy.deepcopy(self.runtime.current(T)['turns'])
        recovered = self.bridge._refresh_job(job['id'])
        self.assertEqual((recovered['state'], recovered['turnId']), ('completed', 'recovered'))
        self.assertEqual(len(self.calls), 2)

    def test_queue_and_nonpaginated_and_stale_turn_reject_before_mutation(self):
        self.queue = [{'id': 'q', 'clientUserMessageId': 'q', 'input': [{'type': 'text', 'text': 'queued'}]}]
        job = self.edit()
        self.assertEqual(job['state'], 'failed'); self.assertEqual(self.calls, [])
        self.queue = []; self.data['requestId'] = 'edit-second'
        self.runtime.current(T)['threadMetadata']['historyMode'] = 'full'
        self.assertEqual(self.edit()['state'], 'failed'); self.assertEqual(self.calls, [])
        self.data['requestId'] = 'edit-third'; self.data['turnId'] = 'old'
        self.assertEqual(self.edit()['state'], 'failed'); self.assertEqual(self.calls, [])


class SettingsProjectionTests(unittest.TestCase):
    def test_desktop_mode_projection_preserves_instructions_and_prefers_settings(self):
        from carryon.sessions.operations import controls
        mode = {'mode': 'plan', 'settings': {'model': 'native', 'developer_instructions': 'preserve'}}
        state = {'latestCollaborationMode': mode}
        self.assertEqual(controls(state)['settings']['collaborationMode'], mode)
        state['latestThreadSettings'] = {'collaborationMode': {'mode': 'default', 'settings': {'model': 'native'}}}
        self.assertEqual(controls(state)['settings']['collaborationMode']['mode'], 'default')
        self.assertIn('activePermissionProfile', controls(state)['supportedSettings'])

    def test_native_capabilities_exclude_read_only_profile_without_hiding_value(self):
        from carryon.sessions.operations import controls
        state = {'supportedSettings': AppServer.supported_settings,
                 'latestThreadSettings': {'activePermissionProfile': {'id': 'read-only'}}}
        self.assertNotIn('activePermissionProfile', controls(state)['supportedSettings'])
        self.assertEqual(controls(state)['settings']['activePermissionProfile']['id'], 'read-only')
