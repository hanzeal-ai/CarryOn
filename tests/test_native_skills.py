import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from carryon.app_server.app_server import AppServer
from carryon.app_server.queue import replace
from carryon.contracts import digest
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.bridge import Bridge
from carryon.sessions.skills import discover, guard_inputs, selections
from carryon.sessions.queue import message
from carryon.sessions.operations import controls
from carryon.owner.requests import input_items
from carryon.store import Journal

T = '11111111-1111-4111-8111-111111111111'


class NativeSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.runtime = AppServer(self.temp.name); self.runtime.process = SimpleNamespace(poll=lambda: None)
        self.runtime.account_ready = True
        self.runtime._event({'method': 'thread/started', 'params': {'thread': {
            'id': T, 'cwd': self.temp.name, 'status': {'type': 'idle'}, 'turns': []}}})
        self.selection = {'name': 'fixture', 'path': self.temp.name + '/SKILL.md'}
        self.metadata = {**self.selection, 'enabled': True, 'description': 'fixture', 'scope': 'repo'}
        self.errors = [{'path': self.temp.name + '/bad', 'message': 'invalid skill'}]
        self.writes = []; self.rows = []; self.hook = lambda: None
        self.runtime.rpc = self.rpc
        self.journal = Journal(Path(self.temp.name) / 'jobs.sqlite'); self.addCleanup(self.journal.conn.close)
        self.bridge = Bridge('unused', SimpleNamespace(get=lambda tid: {}), self.journal)
        self.bridge.ipc = self.runtime; self.bridge.enabled = True

    def rpc(self, method, params, before_send=None, **kwargs):
        if method == 'skills/list':
            self.assertEqual(params, {'cwds': [self.temp.name], 'forceReload': True})
            self.hook()
            return {'data': [{'cwd': self.temp.name, 'skills': [self.metadata], 'errors': self.errors}]}
        if method == 'thread/queue/list': return {'data': self.rows}
        write = lambda: self.writes.append((method, copy.deepcopy(params)))
        if before_send: before_send(write)
        else: write()
        if method == 'turn/start': return {'turn': {'id': 'started', 'status': 'inProgress', 'items': []}}
        return {}

    def test_discovery_preserves_errors_and_requires_loaded_native(self):
        self.assertEqual(discover(self.bridge, T), {'cwd': self.temp.name, 'skills': [self.metadata], 'errors': self.errors})
        self.assertTrue(controls(self.runtime.current(T))['supportsSkills'])
        self.runtime.current(T)['_metadataOnly'] = True
        self.assertFalse(controls(self.runtime.current(T))['supportsSkills'])
        with self.assertRaises(IPCError): discover(self.bridge, T)
        self.bridge.ipc = SimpleNamespace(connected=True)
        with self.assertRaises(IPCError): discover(self.bridge, T)

    def test_unlisted_disabled_and_changed_cwd_never_write(self):
        for selection in [{**self.selection, 'path': '/tmp/unlisted/SKILL.md'}, self.selection]:
            self.metadata['enabled'] = False
            with self.assertRaises(IPCError):
                self.runtime.start(T, '', '', 'id', lambda write: write(), skills=[selection])
        self.metadata['enabled'] = True
        guard = guard_inputs(self.runtime, T, [{'type': 'skill', **self.selection}])
        self.runtime.current(T)['cwd'] = '/tmp/changed'
        with self.assertRaises(IPCError): guard(lambda: self.writes.append('bad'))
        self.assertEqual(self.writes, [])

    def test_skill_only_compose_and_idempotency(self):
        job = self.bridge.compose(T, 'skill-once', '', skills=[self.selection])
        self.assertEqual(job['state'], 'accepted', job)
        self.assertEqual(job['skills'], [self.selection])
        self.assertEqual(self.writes[0][1]['input'], [{'type': 'skill', **self.selection}])
        self.assertEqual(self.bridge.compose(T, 'skill-once', '', skills=[self.selection]), job)
        self.assertEqual(len(self.writes), 1)
        with self.assertRaises(Exception): self.bridge.compose(T, 'skill-once', '', skills=[{**self.selection, 'name': 'other'}])

    def test_queue_add_and_text_edit_keep_native_skill(self):
        desired = [message('', self.runtime.current(T), skills=[self.selection])]
        replace(self.runtime, T, desired, digest([]))
        self.assertEqual(self.writes[-1][1]['input'], [{'type': 'skill', **self.selection}])
        self.rows = [{'id': 'row', 'clientUserMessageId': 'client', 'input': self.writes[-1][1]['input']}]
        current = self.runtime.queue_snapshot(T, refresh=True)
        edited = copy.deepcopy(current); edited[0]['text'] = 'edit'; edited[0]['context']['prompt'] = 'edit'
        replace(self.runtime, T, edited, digest(current))
        self.assertEqual(self.writes[-1][1]['input'][-1], {'type': 'skill', **self.selection})

    def test_bounds_and_owner_shape_reject_untrusted_paths(self):
        for value in [[self.selection] * 21, [self.selection] * 2, [{'name': 'x', 'path': 'relative'}]]:
            with self.assertRaises(ValueError): selections(value)
        self.assertEqual(input_items([{'type': 'skill', **self.selection}]), [{'type': 'skill', **self.selection}])
        with self.assertRaises(ValueError): input_items([{'type': 'skill', **self.selection, 'enabled': True}])
        with self.assertRaises(ValueError): self.bridge.compose(T, 'side', '', parent_id=T, skills=[self.selection])
