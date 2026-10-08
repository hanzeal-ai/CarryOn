"""Creation authorization and the production console's late-reply boundary."""
import io
import json
import threading
import time
import unittest
from types import SimpleNamespace

from carryon.cloud.console import ConsoleHandler
from carryon.workspaces.workspace_access import required_capabilities, require


class CreationCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.members = {'member': ['view', 'create']}
        self.server = SimpleNamespace(
            sessions={'session': time.monotonic() + 60},
            auth=SimpleNamespace(identity=lambda key: 'member'),
            config={'devices': {'device': {'members': self.members}}},
            auth_lock=threading.RLock(), lock=threading.RLock())

    def test_plain_get_is_a_tuple_and_view_grant_is_sufficient(self):
        self.members['member'] = ['view']
        for path in ['/api/status', '/api/threads', '/api/threads/thread/skills']:
            needed = required_capabilities('GET', path)
            self.assertEqual(needed, ('view',))
            require(self.server, 'session', 'device', needed)

    def test_model_effort_do_not_require_edit(self):
        for settings in [None, {'model': 'fixture'}, {'effort': 'high'}]:
            needed = required_capabilities('POST', '/api/threads', {'settings': settings})
            self.assertEqual(needed, ('create',))
            require(self.server, 'session', 'device', needed)

    def test_advanced_keys_even_null_require_both_grants(self):
        for field in ['collaborationMode', 'approvalPolicy', 'sandboxPolicy', 'permissions', 'serviceTier']:
            for value in [None, 'fixture']:
                with self.subTest(field=field, value=value):
                    needed = required_capabilities('POST', '/api/threads', {'settings': {field: value}})
                    self.assertEqual(needed, ('create', 'edit'))
                    self.members['member'] = ['view', 'create']
                    with self.assertRaises(PermissionError):
                        require(self.server, 'session', 'device', needed)
                    self.members['member'] = ['view', 'edit']
                    with self.assertRaises(PermissionError):
                        require(self.server, 'session', 'device', needed)
                    self.members['member'] = ['view', 'create', 'edit']
                    require(self.server, 'session', 'device', needed)

    def test_production_console_reply_marks_late_edit_revocation_uncertain(self):
        needed = required_capabilities('POST', '/api/threads', {'settings': {'approvalPolicy': None}})
        self.members['member'] = ['view', 'create', 'edit']
        require(self.server, 'session', 'device', needed)
        # Exercise the actual reply implementation without opening a listener.
        handler = object.__new__(ConsoleHandler)
        handler.server = self.server
        handler.access_context = ('session', 'device', needed)
        handler.forwarded_write = True
        handler.wfile = io.BytesIO()
        statuses = []
        handler.send_response = statuses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        self.members['member'].remove('edit')
        handler.reply(200, {'state': 'completed', 'createdThreadId': 'child'})
        body = json.loads(handler.wfile.getvalue())
        self.assertEqual(statuses, [409])
        self.assertTrue(body['uncertain'])
        self.assertIn('requestId', body['error'])
        self.assertNotIn('state', body)
