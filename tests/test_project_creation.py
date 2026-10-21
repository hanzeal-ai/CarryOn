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
from carryon.sessions.catalog import Catalog
from native_project_fixture import write_projects
from carryon.errors import BridgeError
from carryon.errors import IPCError
from carryon.store import Journal
from carryon.workspaces.workspace import project_identity
from test_bridge import FakeIPC, CHILD
from test_owner import Runtime, Bus, state


class ProjectCatalog(Catalog):
    def get(self, tid): return {'id': tid, 'created_at': time.time()}
    def list(self, *args): return []


class Creator(Runtime):
    hook = None
    error = None
    instances = []
    def queue_snapshot(self, tid, refresh=False):
        return {'items': []}
    def request(self, method, params, before_send):
        self.last_settings = params['threadSettings']
        before_send(lambda: self.calls.append(('thread/settings/update', params)))
        return {'result': {'applied': True}}
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
    def start(self, tid, prompt, owner, message_id, before_send, images=None):
        result = []
        def send():
            result.append(self.manager.handle({'method': 'thread-follower-start-turn', 'version': 2,
                'requestId': 'wire', 'sourceClientId': 'follower', 'params': {'conversationId': tid,
                'turnStart': {'request': {'threadId': tid, 'clientUserMessageId': message_id,
                'input': ([{'type': 'text', 'text': prompt}] if prompt else []) + [{'type': 'image', 'url': url} for url in (images or [])]}, 'context': {'inheritThreadSettings': True}}}}))
        before_send(send)
        return result[0]['result']['turn']


class ProjectCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.state = self.home / '.codex-global-state.json'
        self.state.write_text(json.dumps({'local-projects': {'obsolete-desktop-id': {'name': 'Old', 'rootPaths': [str(self.home)]}}}))
        write_projects(self.home, {'native-project': {'name': 'Current', 'rootPaths': [str(self.home)]}})
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
    def test_projectless_creation_uses_private_directory_without_native_membership(self):
        job = self.settled(submit(self.bridge, 'no-project', 'hello', None))
        self.assertEqual(job['state'], 'completed', job)
        params = Creator.instances[0].calls[0][1]
        self.assertIsNone(params['projectId'])
        self.assertEqual(params['cwd'], str(self.manager.directory / 'tasks' / 'no-project'))
        self.assertTrue(Path(params['cwd']).is_dir())
        self.assertEqual(submit(self.bridge, 'no-project', 'hello', None), job)
        self.assertEqual(len(Creator.instances), 1)
        self.assertTrue(self.bridge.status()['supportsProjectlessCreation'])

    def test_projectless_upload_destination_and_recent_group_are_equivalent(self):
        from carryon.uploads import target_identity
        expected = {'type': 'creation', 'projectId': None}
        self.assertEqual(target_identity(self.bridge, {'type': 'creation'}), expected)
        self.assertEqual(target_identity(self.bridge, {'type': 'creation', 'projectId': project_identity(None)[0]}), expected)
        job = self.settled(submit(self.bridge, 'recent-create', 'hello', project_identity(None)[0]))
        self.assertEqual(job['state'], 'completed', job)
        self.assertIsNone(Creator.instances[0].calls[0][1]['projectId'])

    def test_projectless_rejects_unexpected_native_membership_before_sending(self):
        original = Creator.create_thread
        def wrong(runtime, params, before_send):
            meta = original(runtime, params, before_send)
            meta['projectId'] = 'unexpected'
            return meta
        with patch.object(Creator, 'create_thread', wrong):
            job = self.settled(submit(self.bridge, 'wrong-membership', 'hello', None))
        self.assertEqual(job['state'], 'uncertain')
        self.assertEqual(job['createdThreadId'], CHILD)
        self.assertEqual([c[0] for c in Creator.instances[0].calls], ['thread/start'])

    def test_same_request_concurrently_creates_once(self):
        entered = threading.Event(); proceed = threading.Event()
        Creator.hook = lambda _: (entered.set(), proceed.wait(2))
        first = submit(self.bridge, 'concurrent-create', 'hello', self.project)
        self.assertTrue(entered.wait(1))
        second = submit(self.bridge, 'concurrent-create', 'hello', self.project)
        self.assertEqual(first['id'], second['id'])
        proceed.set(); self.assertEqual(self.settled(first)['state'], 'completed')
        self.assertEqual(len(Creator.instances), 1)
    def test_image_only_creation_preserves_input_and_retry_identity(self):
        image = 'data:image/png;base64,iVBORw0KGgo='
        job = self.settled(submit(self.bridge, 'image-create', '', self.project, images=[image]))
        self.assertEqual(job['state'], 'completed')
        self.assertEqual(Creator.instances[0].calls[1][1]['input'], [{'type': 'image', 'url': image}])
        self.assertEqual(submit(self.bridge, job['id'], '', self.project, images=[image]), job)
        with self.assertRaises(BridgeError): submit(self.bridge, job['id'], 'changed', self.project, images=[image])
        self.assertEqual(len(Creator.instances), 1)
    def test_selected_model_is_applied_before_first_turn(self):
        settings = {'model': 'fixture', 'effort': 'high'}
        job = self.settled(submit(self.bridge, 'model-create', 'task', self.project, settings=settings))
        self.assertEqual(job['state'], 'completed')
        self.assertEqual([call[0] for call in Creator.instances[0].calls], ['thread/start', 'thread/settings/update', 'turn/start'])
        self.assertEqual(Creator.instances[0].last_settings, settings)
        with self.assertRaises(BridgeError): submit(self.bridge, job['id'], 'task', self.project, settings={'model': 'other'})
    def test_creation_settings_cannot_change_destination_or_readonly_fields(self):
        for key, value in [('cwd', '/other'), ('projectId', 'other'), ('activePermissionProfile', None), ('multiAgentMode', None)]:
            with self.assertRaises(ValueError): submit(self.bridge, 'bad-settings', 'task', self.project, settings={key: value})
        self.assertEqual(Creator.instances, [])

    def test_native_configuration_is_applied_before_first_turn(self):
        config = {'model': 'fixture', 'effort': 'high', 'approvalPolicy': 'on-request',
                  'collaborationMode': {'mode': 'plan', 'settings': {'model': 'fixture', 'reasoning_effort': 'high', 'developer_instructions': None}}}
        job = self.settled(submit(self.bridge, 'configured-create', 'task', self.project, settings=config))
        self.assertEqual(job['state'], 'completed')
        self.assertEqual(Creator.instances[0].last_settings, config)
        self.assertEqual([call[0] for call in Creator.instances[0].calls], ['thread/start', 'thread/settings/update', 'turn/start'])

    def test_revoked_between_configuration_and_first_turn_retains_created_id(self):
        allowed = [True]
        def authorize():
            if not allowed[0]: raise BridgeError('revoked', 403)
        original = Creator.request
        def configure(runtime, method, params, before_send):
            result = original(runtime, method, params, before_send)
            allowed[0] = False
            return result
        with patch.object(Creator, 'request', configure):
            job = self.settled(submit(self.bridge, 'configured-revoked', 'task', self.project, settings={'approvalPolicy': 'on-request'}, authorize=authorize))
        self.assertEqual(job['state'], 'uncertain')
        self.assertEqual(job['createdThreadId'], CHILD)
        self.assertFalse(any(call[0] == 'turn/start' for call in Creator.instances[0].calls))
        self.assertEqual(submit(self.bridge, job['id'], 'task', self.project, settings={'approvalPolicy': 'on-request'})['id'], job['id'])
        self.assertEqual(len(Creator.instances), 1)
    def test_invalid_project_and_missing_directory_do_not_start_runtime(self):
        for project in ('', project_identity('/other')[0]):
            with self.assertRaises((ValueError, BridgeError)): submit(self.bridge, 'bad-project', 'hello', project)
        # Keep the catalog database accessible while the project's root is missing.
        missing_root = self.home / 'missing-project'
        write_projects(self.home, {'native-project': {'name': 'Current', 'rootPaths': [str(missing_root)]}})
        missing_project = project_identity(str(missing_root), native_id='native-project')[0]
        with self.assertRaisesRegex(BridgeError, '项目目录已不可用'):
            submit(self.bridge, 'bad-directory', 'hello', missing_project)
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
        Creator.hook = lambda _: write_projects(self.home, {})
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
        self.assertEqual(job['state'], 'uncertain')
        self.assertEqual([call[0] for call in Creator.instances[0].calls], ['thread/start', 'thread/backgroundTerminals/list'])
        self.assertEqual(Creator.instances[0].calls[1][1], {'threadId': CHILD, 'limit': 1})
        self.assertFalse(Creator.instances[0].connected); self.assertEqual(self.manager.entries, {})
    def test_lost_turn_reply_retains_owner_and_does_not_replay(self):
        original = self.bridge.ipc.start
        def start(*args, **kwargs):
            original(*args, **kwargs); raise IPCError('lost turn', uncertain=True)
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

    def test_obsolete_desktop_project_id_is_rejected_before_creating(self):
        stale = project_identity(str(self.home), native_id='obsolete-desktop-id')[0]
        with self.assertRaises(BridgeError): submit(self.bridge, 'stale-project', 'task', stale)
        self.assertEqual(Creator.instances, [])

    def test_create_uses_native_project_without_desktop_json(self):
        self.state.unlink()
        job = self.settled(submit(self.bridge, 'native-project-only', 'task', self.project))
        self.assertEqual(job['state'], 'completed')
        self.assertEqual(Creator.instances[0].calls[0][1]['projectId'], 'native-project')
