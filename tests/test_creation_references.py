"""Discovery is bound to the authorized destination and native session."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from carryon.sessions.creation_references import discover
from carryon.errors import BridgeError
from carryon.errors import IPCError
from carryon.workspaces.workspace import project_identity


class Runtime(SimpleNamespace):
    @property
    def connection_identity(self):
        return self.process, self.session_id


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = Runtime(process=object(), session_id='initial', connected=True, require_account=lambda: None)
        self.bridge = SimpleNamespace(lock=threading.RLock(), catalog=SimpleNamespace(home=self.root, independent=True),
                                      workspace_directory=self.root, require=lambda: (self.runtime, 1), check_generation=lambda *_: None)
        self.skill = {'name': 'review', 'path': '/skill/SKILL.md', 'enabled': True}
        self.skills = patch('carryon.sessions.creation_references.skills.catalog', return_value={'skills': [self.skill], 'errors': []}).start()
        self.mentions = patch('carryon.sessions.creation_references.mentions.catalog', return_value={'mentions': [], 'errors': []}).start()
        self.addCleanup(patch.stopall)
    def test_direct_discovery_without_creating_thread(self):
        result = discover(self.bridge)
        self.assertEqual(result['skills'], [self.skill]); self.assertEqual(Path(result['cwd']).parent, self.root / 'tasks')
        self.assertFalse(Path(result['cwd']).exists())
        self.skills.assert_called_once_with(self.runtime, result['cwd'])
    def test_direct_rejects_project(self):
        with self.assertRaises(BridgeError): discover(self.bridge, project_identity('/other')[0])
        self.skills.assert_not_called()
    def test_session_change_or_disconnect_cannot_publish_old_catalog(self):
        for attr, value in [('session_id', 'replacement'), ('process', object()), ('connected', False)]:
            before = getattr(self.runtime, attr)
            def change(*_):
                setattr(self.runtime, attr, value)
                return {'mentions': [], 'errors': []}
            self.mentions.side_effect = change
            with self.assertRaises(IPCError): discover(self.bridge)
            setattr(self.runtime, attr, before)
    def test_revocation_during_read(self):
        allowed = [True]
        def authorize():
            if not allowed[0]: raise BridgeError('revoked', 403)
        self.mentions.side_effect = lambda *_: (allowed.__setitem__(0, False) or {'mentions': [], 'errors': []})
        with self.assertRaises(BridgeError): discover(self.bridge, authorize=authorize)
    def test_owner_project_change_closes_temporary_runtime(self):
        self.bridge.catalog.independent = False
        state = self.root / '.codex-global-state.json'
        state.write_text(json.dumps({'local-projects': {'native': {'rootPaths': [str(self.root)]}}}))
        project = project_identity(str(self.root), native_id='native')[0]
        closed = []
        self.runtime.connect = lambda: None; self.runtime.close = lambda: closed.append(True)
        self.bridge.owners = lambda: SimpleNamespace(directory=self.root / 'owner', runtime_factory=lambda *a, **k: self.runtime)
        self.mentions.side_effect = lambda *_: (state.write_text('{"local-projects":{}}') and {'mentions': [], 'errors': []})
        with self.assertRaises(BridgeError): discover(self.bridge, project)
        self.assertEqual(closed, [True]); self.assertEqual(list((self.root / 'owner').iterdir()), [])
