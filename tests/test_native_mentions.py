"""Native reference boundary: inventory authorization, routing and preservation."""
import copy
import test_native_skills as fixture
T = fixture.T
from carryon.sessions.mentions import discover, guard_inputs, selections
from carryon.sessions.queue import message
from carryon.sessions.operations import controls
from carryon.app_server.queue import replace
from carryon.contracts import digest
from carryon.desktop_ipc.ipc import IPCError
from carryon.owner.requests import input_items
import unittest


class NativeMentionsTests(fixture.NativeSkillsTests):
    # Reuse only the runtime fixture; inherited skill cases still check composition of both guards.
    def setUp(self):
        super().setUp()
        self.app = {'id': 'fixture-app', 'name': 'Fixture App', 'isAccessible': True, 'isEnabled': True}
        self.plugin = {'id': 'fixture@local', 'name': 'Fixture Plugin', 'installed': True, 'enabled': True, 'availability': 'AVAILABLE'}
        self.app_error = False

    def rpc(self, method, params, before_send=None, **kwargs):
        if method == 'plugin/installed':
            self.assertEqual(params, {'cwds': [self.temp.name]})
            return {'marketplaces': [{'name': 'local', 'plugins': [self.plugin]}], 'marketplaceLoadErrors': []}
        if method == 'app/list':
            self.assertTrue(params['forceRefetch'])
            if self.app_error: raise IPCError('isolated application inventory failure')
            return {'data': [self.app]}
        return super().rpc(method, params, before_send, **kwargs)

    def test_inventory_partial_failure_and_flags(self):
        result = discover(self.bridge, T)
        self.assertEqual([r['path'] for r in result['mentions']], ['plugin://fixture@local', 'app://fixture-app'])
        self.assertTrue(controls(self.runtime.current(T))['supportsMentions'])
        self.app_error = True
        result = discover(self.bridge, T)
        self.assertEqual(len(result['mentions']), 1); self.assertEqual(result['errors'][0]['source'], 'apps')

    def test_mentions_only_compose_and_repeat_identity(self):
        selected = [{'name': 'Fixture App', 'path': 'app://fixture-app'}]
        job = self.bridge.compose(T, 'mention-once', '', mentions=selected)
        self.assertEqual(job['state'], 'accepted', job)
        self.assertEqual(self.writes[0][1]['input'], [{'type': 'mention', **selected[0]}])
        self.assertEqual(self.bridge.compose(T, 'mention-once', '', mentions=selected), job)
        with self.assertRaises(Exception): self.bridge.compose(T, 'mention-once', '', mentions=[{'name': 'other', 'path': selected[0]['path']}])
        self.assertEqual(len(self.writes), 1)

    def test_revoked_inventory_and_runtime_change_prevent_write(self):
        selected = [{'name': 'Fixture App', 'path': 'app://fixture-app'}]
        self.app['isAccessible'] = False
        job = self.bridge.compose(T, 'revoked-once', '', mentions=selected)
        self.assertEqual(job['state'], 'failed'); self.assertEqual(self.writes, [])
        self.app['isAccessible'] = True
        guard = guard_inputs(self.runtime, T, [{'type': 'mention', **selected[0]}])
        self.runtime.current(T)['cwd'] = '/changed'
        with self.assertRaises(IPCError): guard(lambda: self.writes.append('invalid'))
        self.assertEqual(self.writes, [])

    def test_queue_edit_preserves_mention_and_rechecks_access(self):
        selected = [{'name': 'Fixture App', 'path': 'app://fixture-app'}]
        replace(self.runtime, T, [message('', self.runtime.current(T), mentions=selected)], digest([]))
        self.assertEqual(self.writes[-1][1]['input'], [{'type': 'mention', **selected[0]}])
        self.rows = [{'id': 'row', 'clientUserMessageId': 'client', 'input': self.writes[-1][1]['input']}]
        current = self.runtime.queue_snapshot(T, refresh=True)
        edited = copy.deepcopy(current); edited[0]['text'] = 'edit'; edited[0]['context']['prompt'] = 'edit'
        replace(self.runtime, T, edited, digest(current))
        self.assertEqual(self.writes[-1][1]['input'][-1], {'type': 'mention', **selected[0]})
        count = len(self.writes); self.app['isEnabled'] = False
        with self.assertRaises(IPCError): replace(self.runtime, T, edited, digest(current))
        self.assertEqual(len(self.writes), count)

    def test_uri_and_owner_validation(self):
        selected = {'name': 'Fixture App', 'path': 'app://fixture-app'}
        self.assertEqual(input_items([{'type': 'mention', **selected}]), [{'type': 'mention', **selected}])
        for path in ('tab://private', '/tmp/file', 'plugin://', 'app://bad\nvalue'):
            with self.assertRaises(ValueError): selections([{'name': 'bad', 'path': path}])
        self.runtime.current(T)['supportsMentions'] = False
        with self.assertRaises(ValueError): self.bridge.compose(T, 'unsupported', '', mentions=[selected])
