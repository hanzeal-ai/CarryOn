import copy
import unittest
from carryon.workspaces.connections import assign_workspaces, descriptor, public_descriptor, validate


class WorkspaceConnectionsTests(unittest.TestCase):
    def test_shared_history_groups_but_service_identity_and_credentials_stay_separate(self):
        records = {'desktop': {'directory': '/desktop', 'name': '电脑', 'backend': 'desktop-ipc', 'codexHome': '/home', 'token': 'd'},
                   'cli': {'directory': '/cli', 'name': 'CLI', 'backend': 'codex-cli', 'codexHome': '/home', 'token': 'c'},
                   'other': {'directory': '/other', 'backend': 'codex-cli', 'codexHome': '/other-home'},
                   'owned': {'directory': '/owned', 'backend': 'app-server', 'codexHome': '/home'}}
        original = copy.deepcopy(records)
        assign_workspaces(records)
        self.assertEqual(records['desktop']['workspaceId'], records['cli']['workspaceId'])
        self.assertEqual(records['cli']['workspaceName'], '电脑')
        self.assertEqual(len({r['workspaceId'] for r in records.values()}), 3)
        for key, row in original.items():
            self.assertEqual({k: records[key][k] for k in row}, row)
        before = copy.deepcopy(records)
        assign_workspaces(records)
        self.assertEqual(records, before)

    def test_cli_first_registration_preserves_workspace_when_desktop_added(self):
        rows = {'cli': {'directory': '/cli', 'name': '电脑', 'backend': 'codex-cli', 'codexHome': '/home'}}
        assign_workspaces(rows)
        identity = rows['cli']['workspaceId']
        rows['desktop'] = {'directory': '/desktop', 'name': 'Desktop', 'backend': 'desktop-ipc', 'codexHome': '/home'}
        assign_workspaces(rows)
        self.assertEqual(rows['desktop']['workspaceId'], identity)

    def test_unbound_legacy_and_removed_connections_do_not_merge(self):
        rows = {'a': {'directory': '/a'}, 'b': {'directory': '/b'}, 'old': {'directory': '/old', 'removed': True}}
        assign_workspaces(rows)
        self.assertNotEqual(rows['a']['workspaceId'], rows['b']['workspaceId'])
        self.assertNotIn('workspaceId', rows['old'])
        self.assertIsNone(descriptor({}))
        self.assertIsNone(public_descriptor({'name': 'legacy'}))

    def test_public_group_is_owner_scoped_and_contains_no_local_paths(self):
        workspace = {'id': 'a' * 32, 'name': '电脑', 'backend': 'codex-cli'}
        a = public_descriptor({'ownerUserId': 'a', 'workspace': workspace})
        b = public_descriptor({'ownerUserId': 'b', 'workspace': workspace})
        self.assertNotEqual(a['id'], b['id'])
        self.assertIsNone(public_descriptor({'workspace': workspace}))
        self.assertEqual(set(a), {'id', 'name', 'backend'})
        self.assertEqual(a, public_descriptor({'ownerUserId': 'a', 'workspace': workspace}))

    def test_invalid_descriptor_rejected(self):
        valid = {'id': 'a' * 32, 'name': '电脑', 'backend': 'codex-cli'}
        for bad in (None, {}, {**valid, 'id': '../../a'}, {**valid, 'name': ''}, {**valid, 'name': 'a' * 101}, {**valid, 'backend': 'desktop'}, {**valid, 'token': 'secret'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): validate(bad)
