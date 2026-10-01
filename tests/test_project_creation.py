import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from carryon.owner.integration import OwnerBridge
from carryon.owner.manager import OwnerManager
from carryon.sessions.creation import submit, resolve_project
from carryon.errors import BridgeError
from carryon.desktop_ipc.ipc import IPCError
from carryon.store import Journal
from carryon.workspaces.workspace import project_identity
from test_bridge import FakeIPC, CHILD
from test_owner import Runtime, Bus, state


class ProjectCatalog:
    def __init__(self, home): self.home = home
    def get(self, tid): return {'id': tid, 'created_at': time.time()}
    def list(self, *args): return []


class Creator(Runtime):
    hook = None
    error = None
    instances = []
    def create_thread(self, params, before_send):
        if self.hook: self.hook()
        before_send(lambda: self.calls.append(('thread/start', params)))
        if self.error: raise self.error
        self.data = state(CHILD)
        self.data['cwd'] = params['cwd']
        self.data['turns'] = []
        meta = {'id': CHILD, 'cwd': params['cwd'], 'projectId': params['projectId'], 'historyMode': 'paginated'}
        self.data['threadMetadata'] = meta
        return meta


class Follower(FakeIPC):
    def snapshot(self, tid):
        return self.manager.bus.client_id, self.manager.entries[tid]['runtime'].current(tid)
    def start(self, tid, prompt, owner, message_id, before_send):
        result = []
        def send():
            result.append(self.manager.handle({'method': 'thread-follower-start-turn', 'version': 2,
                'requestId': 'wire', 'sourceClientId': 'follower', 'params': {'conversationId': tid,
                'turnStart': {'request': {'threadId': tid, 'clientUserMessageId': message_id,
                'input': [{'type': 'text', 'text': prompt}]}, 'context': {'inheritThreadSettings': True}}}}))
        before_send(send)
        return result[0]['result']['turn']


class ProjectCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.state = self.home / '.codex-global-state.json'
        self.state.write_text(json.dumps({'local-projects': {'native-project': {'rootPaths': [str(self.home)]}}}))
        self.project = project_identity(str(self.home), native_id='native-project')[0]
        self.journal = Journal(self.home / 'jobs.sqlite')
        self.bridge = OwnerBridge('fake', ProjectCatalog(self.home), self.journal,
                                  owner_directory=self.home / 'owner', ipc_factory=Follower)
        self.manager = OwnerManager(self.home, self.home / 'owner', self.bridge.catalog,
                                    runtime_factory=Creator, transport_factory=Bus)
        self.bridge.owner_service = self.manager
        self.bridge.enable()
        self.bridge.ipc.manager = self.manager
        with self.manager.prewarm.condition:
            self.assertTrue(self.manager.prewarm.condition.wait_for(lambda: self.manager.prewarm.worker is None, timeout=2))
        Creator.instances = []; Creator.hook = None; Creator.error = None
    def tearDown(self):
        self.bridge.shutdown(); self.journal.conn.close(); self.temp.cleanup()
    def settled(self, job):
        for _ in range(200):
            result = self.journal.get(job['id'])
            if result['state'] not in ('preparing', 'dispatching'): return result
            time.sleep(.01)
        self.fail('job did not settle')
    def test_native_project_identity_and_membership(self):
        self.assertEqual(resolve_project(self.bridge.catalog, self.project)['id'], 'native-project')
        with self.assertRaises(BridgeError): resolve_project(self.bridge.catalog, project_identity('/other')[0])
    def test_create_without_existing_conversations_and_send_exact_prompt_through_owner(self):
        prompt = '请修复按钮。\n保留输入内容。'
        job = self.settled(submit(self.bridge, 'project-create-1', prompt, self.project))
        self.assertEqual(job['state'], 'completed')
        self.assertEqual(job['threadId'], CHILD)
        self.assertEqual(job['createdThreadId'], CHILD)
        runtime = Creator.instances[0]
        self.assertEqual(runtime.calls[0], ('thread/start', {'cwd': str(self.home), 'projectId': 'native-project', 'historyMode': 'paginated'}))
        self.assertEqual(runtime.calls[1][0], 'turn/start')
        self.assertEqual(runtime.calls[1][1]['input'], [{'type': 'text', 'text': prompt}])
        self.assertTrue(runtime.connected)
        self.assertIs(self.manager.entries[CHILD]['runtime'], runtime)
        again = submit(self.bridge, job['id'], prompt, self.project)
        self.assertEqual(again, job); self.assertEqual(len(Creator.instances), 1)
        with self.assertRaises(BridgeError): submit(self.bridge, job['id'], 'different', self.project)
    def test_same_request_concurrently_creates_once(self):
        entered = threading.Event(); proceed = threading.Event()
        Creator.hook = lambda _: (entered.set(), proceed.wait(2))
        first = submit(self.bridge, 'concurrent-create', 'hello', self.project)
        self.assertTrue(entered.wait(1))
        second = submit(self.bridge, 'concurrent-create', 'hello', self.project)
        self.assertEqual(first['id'], second['id'])
        proceed.set(); self.assertEqual(self.settled(first)['state'], 'completed')
        self.assertEqual(len(Creator.instances), 1)
    def test_invalid_project_and_missing_directory_do_not_start_runtime(self):
        for project in (None, project_identity('/other')[0]):
            with self.assertRaises((ValueError, BridgeError)): submit(self.bridge, 'bad-project', 'hello', project)
        with patch('carryon.sessions.creation.Path.is_dir', return_value=False):
            with self.assertRaises(BridgeError): submit(self.bridge, 'bad-directory', 'hello', self.project)
        self.assertEqual(Creator.instances, [])
    def test_revocation_before_create_has_no_native_write(self):
        allowed = [True]
        def authorize():
            if not allowed[0]: raise BridgeError('revoked', 403)
        Creator.hook = lambda _: allowed.__setitem__(0, False)
        job = self.settled(submit(self.bridge, 'revoked-create', 'hello', self.project, authorize=authorize))
        self.assertEqual(job['state'], 'failed'); self.assertEqual(Creator.instances[0].calls, [])
        self.assertFalse(Creator.instances[0].connected)
    def test_project_change_before_write_blocks_creation(self):
        Creator.hook = lambda _: self.state.write_text(json.dumps({'local-projects': {}}))
        job = self.settled(submit(self.bridge, 'changed-project', 'hello', self.project))
        self.assertEqual(job['state'], 'failed'); self.assertEqual(Creator.instances[0].calls, [])
    def test_lost_creation_reply_is_uncertain_and_never_recreated(self):
        Creator.error = IPCError('lost reply', uncertain=True)
        job = self.settled(submit(self.bridge, 'lost-create', 'hello', self.project))
        self.assertEqual(job['state'], 'uncertain'); self.assertFalse(Creator.instances[0].connected)
        self.assertEqual(submit(self.bridge, job['id'], 'hello', self.project), job)
        self.assertEqual(len(Creator.instances), 1)
    def test_native_rejection_is_failed(self):
        Creator.error = IPCError('project not found')
        job = self.settled(submit(self.bridge, 'rejected-create', 'hello', self.project))
        self.assertEqual(job['state'], 'failed'); self.assertFalse(Creator.instances[0].connected)
    def test_owner_conflict_preserves_id_without_sending(self):
        self.manager.bus.foreign = 'desktop'
        job = self.settled(submit(self.bridge, 'conflict-create', 'hello', self.project))
        self.assertEqual(job['state'], 'uncertain'); self.assertEqual(job['createdThreadId'], CHILD)
        self.assertEqual(len(Creator.instances[0].calls), 1); self.assertFalse(Creator.instances[0].connected)
        self.assertEqual(self.manager.entries, {})
    def test_revoke_after_adoption_releases_idle_runtime_without_sending(self):
        allowed = [True]
        def authorize():
            if not allowed[0]: raise BridgeError('revoked', 403)
        original = self.bridge.ipc.snapshot
        def snapshot(tid):
            result = original(tid); allowed[0] = False; return result
        self.bridge.ipc.snapshot = snapshot
        job = self.settled(submit(self.bridge, 'revoke-adopt', 'hello', self.project, authorize=authorize))
        self.assertEqual(job['state'], 'uncertain'); self.assertEqual(len(Creator.instances[0].calls), 1)
        self.assertFalse(Creator.instances[0].connected); self.assertEqual(self.manager.entries, {})
    def test_lost_turn_reply_retains_owner_and_does_not_replay(self):
        original = self.bridge.ipc.start
        def start(*args):
            original(*args); raise IPCError('lost turn', uncertain=True)
        self.bridge.ipc.start = start
        job = self.settled(submit(self.bridge, 'lost-turn', 'hello', self.project))
        self.assertEqual(job['state'], 'uncertain'); self.assertTrue(Creator.instances[0].connected)
        self.assertEqual(submit(self.bridge, job['id'], 'hello', self.project), job)
        self.assertEqual(len(Creator.instances[0].calls), 2)
    def test_explicit_turn_rejection_releases_idle_creator(self):
        def rejected(*args):
            args[-1](lambda: None)
            raise IPCError('turn rejected')
        self.bridge.ipc.start = rejected
        job = self.settled(submit(self.bridge, 'rejected-turn', 'hello', self.project))
        self.assertEqual(job['state'], 'uncertain')
        self.assertEqual(job['createdThreadId'], CHILD)
        # Cleanup can finish just after the receipt becomes visible.
        for _ in range(100):
            if not Creator.instances[0].connected: break
            time.sleep(.01)
        self.assertFalse(Creator.instances[0].connected)
        self.assertEqual(self.manager.entries, {})
    def test_cloud_scoping_and_read_only_permission(self):
        from carryon.routes.remote_scope import scoped_dispatch, request_key
        body = {'projectId': self.project, 'requestId': 'cloud-project-1', 'prompt': 'hello'}
        with self.assertRaises(BridgeError): scoped_dispatch(self.bridge, 'POST', '/api/threads', body, False, 'binding-a')
        status, job = scoped_dispatch(self.bridge, 'POST', '/api/threads', body, True, 'binding-a')
        self.assertEqual(status, 202); self.assertEqual(job['id'], body['requestId'])
        stored = self.settled({'id': request_key('binding-a', body['requestId'])})
        self.assertEqual(stored['sourceBinding'], 'binding-a'); self.assertEqual(stored['state'], 'completed')
        with self.assertRaises(BridgeError): scoped_dispatch(self.bridge, 'GET', '/api/jobs/' + body['requestId'], None, True, 'binding-b')
