import json
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from carryon.bridge import Bridge
from carryon.catalog import Catalog
from carryon.creation import submit, resolve_project, belongs
from carryon.errors import BridgeError
from carryon.ipc import IPCError
from carryon.store import Journal
from carryon.workspace import project_identity
from test_bridge import FakeIPC, THREAD, CHILD

BUSY='33333333-3333-4333-8333-333333333333'

class ProjectCatalog:
    def __init__(self, home):
        self.home=home
        self.rows=[{'id':BUSY,'cwd':'/project','projectRoot':'/project'}, {'id':THREAD,'cwd':'/project','projectRoot':'/project'}]
    def get(self, tid):return {'id':tid,'created_at':time.time()}
    def list(self, *args):return self.rows

class Native(FakeIPC):
    def __init__(self, path):
        super().__init__(path);self.prompts=[]
        self.states={BUSY:{'id':BUSY,'threadRuntimeStatus':{'type':'active'},'requests':[]},
                     THREAD:{'id':THREAD,'threadRuntimeStatus':{'type':'idle'},'requests':[]}}
    def current(self, tid):return self.states.get(tid)
    def snapshot(self, tid):
        if tid not in self.states: raise IPCError('no-client-found')
        return 'owner',self.states[tid]
    def wake_snapshot(self, tid, *, before_open):
        before_open()
        return self.snapshot(tid)
    sidebar_snapshot=snapshot
    def start(self, tid, prompt, owner, message_id, before_send):
        before_send(lambda:self.prompts.append((tid,prompt)))
        return {'id':'turn-1'}

class ProjectCreationTests(unittest.TestCase):
    def test_native_identity_resolves_shared_root_and_checks_created_membership(self):
        self.state.write_text(json.dumps({'local-projects':{
            'bundle':{'name':'Bundle','rootPaths':['/project','/second']},
            'other':{'rootPaths':['/project']}}}))
        pid=project_identity('/project',native_id='bundle')[0]
        project=resolve_project(self.bridge.catalog,pid)
        self.assertEqual(project,{'id':'bundle','cwd':'/project','groupId':pid,'isGitRepository':True})
        self.assertTrue(belongs({'nativeProjectId':'bundle','cwd':'/second'},project))
        self.assertFalse(belongs({'nativeProjectId':'other','cwd':'/project'},project))
        self.assertFalse(belongs({'nativeProjectId':'bundle','projectless':True},project))
        with self.assertRaises(BridgeError):resolve_project(self.bridge.catalog,project_identity('/project')[0])
        legacy=resolve_project(self.bridge.catalog,project_identity('/second')[0])
        self.assertEqual(legacy['id'],'bundle')
        self.assertTrue(belongs({'nativeProjectId':'bundle','cwd':'/second'},legacy))
        self.state.write_text(json.dumps({'local-projects':{'bundle':{'rootPaths':['/second','/second']}}}))
        self.assertEqual(resolve_project(self.bridge.catalog,project_identity('/second')[0])['id'],'bundle')

    def setUp(self):
        git_state = patch('carryon.creation.is_git_repository', return_value=True)
        git_state.start(); self.addCleanup(git_state.stop)
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.state=self.home/'.codex-global-state.json'
        self.state.write_text(json.dumps({'local-projects':{'native-project':{'rootPaths':['/project']}}}))
        self.project=project_identity('/project')[0]
        self.journal=Journal(self.home/'jobs.sqlite')
        self.bridge=Bridge('fake',ProjectCatalog(self.home),self.journal,Native);self.bridge.enable()
    def tearDown(self):self.bridge.disable();self.journal.conn.close();self.temp.cleanup()
    def settled(self, job):
        for _ in range(100):
            result=self.journal.get(job['id'])
            if result['state'] not in ('preparing','dispatching'):return result
            time.sleep(.01)
        self.fail('job did not settle')
    def test_selects_idle_project_member_and_passes_prompt_without_global_controller(self):
        prompt='请修复按钮。\n保留输入内容。'
        job=submit(self.bridge,'project-create-1',prompt,self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertIsNone(self.bridge.controller)
        tid,payload=self.bridge.ipc.prompts[0]
        self.assertEqual(tid,THREAD)
        self.assertIn(json.dumps(prompt,ensure_ascii=False),payload)
        self.assertIn('native-project',payload)
        self.assertIn('list_projects',payload)
        self.assertNotIn('"type":"projectless"',payload)
        self.assertEqual(submit(self.bridge,'project-create-1',prompt,self.project)['id'],job['id'])
        self.assertEqual(len(self.bridge.ipc.prompts),1)
        with self.assertRaises(BridgeError):submit(self.bridge,'project-create-1','different',self.project)
    def test_rejects_missing_project_busy_and_unowned_candidates(self):
        with self.assertRaises(BridgeError):submit(self.bridge,'project-create-1','hello',project_identity('/other')[0])
        self.bridge.ipc.states[THREAD]['threadRuntimeStatus']['type']='active'
        with self.assertRaises(BridgeError):submit(self.bridge,'project-create-2','hello',self.project)
        self.assertEqual(self.bridge.ipc.prompts,[])
    def test_pending_jobs_are_not_selected(self):
        self.journal.insert({'id':'pending','kind':'message','fingerprint':'f','threadId':THREAD,'state':'uncertain','created':time.time()})
        with self.assertRaises(BridgeError):submit(self.bridge,'project-create-1','hello',self.project)
    def test_revocation_prevents_dispatch(self):
        def denied():raise BridgeError('revoked',403)
        with self.assertRaises(BridgeError):submit(self.bridge,'project-create-1','hello',self.project,authorize=denied)
        self.assertEqual(self.bridge.ipc.prompts,[])
    def test_state_change_before_native_write_blocks_creation(self):
        native_start=self.bridge.ipc.start
        def changed(tid, *args, **kwargs):
            self.bridge.ipc.states[tid]['threadRuntimeStatus']['type']='active'
            return native_start(tid,*args,**kwargs)
        self.bridge.ipc.start=changed
        job=submit(self.bridge,'project-create-1','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'failed')
        self.assertEqual(self.bridge.ipc.prompts,[])
    def test_project_change_before_native_write_blocks_creation(self):
        native_start=self.bridge.ipc.start
        def changed(tid, *args, **kwargs):
            self.bridge.catalog.rows=[]
            return native_start(tid,*args,**kwargs)
        self.bridge.ipc.start=changed
        job=submit(self.bridge,'project-create-1','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'failed')
        self.assertEqual(self.bridge.ipc.prompts,[])
    def test_cloud_project_creation_uses_scoped_request_and_preserves_project(self):
        from carryon.remote_scope import scoped_dispatch, request_key
        body={'projectId':self.project,'requestId':'cloud-project-1','prompt':'hello'}
        status,job=scoped_dispatch(self.bridge,'POST','/api/threads',body,True,'binding-a')
        self.assertEqual(status,202)
        stored=self.settled({'id':request_key('binding-a','cloud-project-1')})
        self.assertEqual(stored['sourceBinding'],'binding-a')
        self.assertEqual(stored['creationProject']['id'],'native-project')
        self.assertEqual(job['id'],'cloud-project-1')
    def test_native_creation_result_must_match_project_and_prompt(self):
        job=submit(self.bridge,'project-create-1','hello',self.project);self.settled(job)
        call={'status':'completed','arguments':{'prompt':'hello','title':job['expectedTitle'],
             'target':{'type':'project','projectId':'wrong','environment':{'type':'worktree'}}},
             'result':{'content':[{'type':'text','text':json.dumps({'hostId':'local','threadId':CHILD})}]}}
        self.bridge.turn_evidence=lambda *args:{'status':'completed','createCalls':[call]}
        self.bridge.catalog.rows.append({'id':CHILD,'cwd':'/worktree','projectRoot':'/project'})
        self.assertEqual(self.bridge.refresh_job(job['id'])['state'],'uncertain')
        call['arguments']['target']['projectId']='native-project'
        call['arguments']['target']['environment'] = {'type': 'local'}
        self.assertEqual(self.bridge.refresh_job(job['id'])['state'],'uncertain')
        call['arguments']['target']['environment'] = {'type': 'worktree', 'startingState': {'type': 'working-tree'}}
        self.assertEqual(self.bridge.refresh_job(job['id'])['state'],'uncertain')
        call['arguments']['target']['environment'] = {'type': 'worktree'}
        self.assertEqual(self.bridge.refresh_job(job['id'])['createdThreadId'],CHILD)
    def test_queued_worktree_id_requires_native_binding(self):
        catalog=Catalog(self.home)
        with self.assertRaises(ValueError):catalog.created_thread_id({'clientThreadId':THREAD})
        self.state.write_text(json.dumps({'electron-persisted-atom-state':{'client-thread-bindings-v1':{THREAD:CHILD}}}))
        self.assertEqual(catalog.created_thread_id({'clientThreadId':THREAD}),CHILD)

    def test_prefixed_queued_worktree_id_resolves_only_through_native_binding(self):
        catalog=Catalog(self.home)
        client_id='client-new-thread:438ce5fa-14b0-495d-a349-a9b5dc84f50f'
        with self.assertRaises(ValueError):catalog.created_thread_id({'clientThreadId':client_id})
        self.state.write_text(json.dumps({'electron-persisted-atom-state':{'client-thread-bindings-v1':{client_id:CHILD}}}))
        self.assertEqual(catalog.created_thread_id({'clientThreadId':client_id}),CHILD)
        for invalid in ['client-new-thread:invalid', 'other:'+THREAD, None]:
            with self.assertRaises(ValueError):catalog.created_thread_id({'clientThreadId':invalid})
        with self.assertRaises(ValueError):catalog.created_thread_id({'threadId':client_id})

    def add_recent(self, tid=CHILD, updated_at=1, runtime='idle'):
        self.bridge.catalog.rows.append({'id':tid,'cwd':'/recent','projectless':True,'updated_at':updated_at})
        self.bridge.ipc.states[tid]={'id':tid,'threadRuntimeStatus':{'type':runtime},'requests':[]}

    def test_recent_projectless_precedes_newer_project_conversation(self):
        self.add_recent()
        self.bridge.catalog.rows[1]['updated_at']=100
        job=submit(self.bridge,'recent-create-1','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertEqual(self.bridge.ipc.prompts[0][0],CHILD)
        self.assertEqual(job['creationProject']['id'],'native-project')
        self.assertIn('native-project',self.bridge.ipc.prompts[0][1])
        self.assertIsNone(self.bridge.controller)
        self.assertEqual(submit(self.bridge,'recent-create-1','hello',self.project)['id'],job['id'])
        self.assertEqual(len(self.bridge.ipc.prompts),1)

    def test_recent_candidates_use_recency_and_skip_busy_waiting_and_uncertain(self):
        self.add_recent(CHILD,updated_at=1)
        self.add_recent(BUSY,updated_at=3,runtime='active')
        waiting='44444444-4444-4444-8444-444444444444'
        self.add_recent(waiting,updated_at=4)
        self.bridge.ipc.states[waiting]['requests']=[{'id':'approval'}]
        pending='55555555-5555-4555-8555-555555555555'
        self.add_recent(pending,updated_at=5)
        self.journal.insert({'id':'pending','kind':'message','fingerprint':'f','threadId':pending,'state':'uncertain','created':time.time()})
        job=submit(self.bridge,'recent-create-2','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertEqual(self.bridge.ipc.prompts[0][0],CHILD)

    def test_falls_back_to_other_project_when_recent_is_busy(self):
        self.add_recent(runtime='active')
        self.bridge.catalog.rows[1].update(cwd='/other',projectRoot='/other')
        job=submit(self.bridge,'recent-create-3','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertEqual(self.bridge.ipc.prompts[0][0],THREAD)
        self.assertEqual(job['creationProject']['id'],'native-project')

    def test_unloaded_recent_is_woken_before_loaded_project_candidate(self):
        self.add_recent(runtime='notLoaded')
        woke=[]
        def wake(tid, *, before_open):
            before_open(); woke.append(tid)
            self.bridge.ipc.states[tid]['threadRuntimeStatus']={'type':'idle'}
            return self.bridge.ipc.snapshot(tid)
        self.bridge.ipc.wake_snapshot=wake
        job=submit(self.bridge,'recent-create-4','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertEqual(woke,[CHILD])
        self.assertEqual(self.bridge.ipc.prompts[0][0],CHILD)

    def test_woken_busy_or_unknown_recent_is_not_used(self):
        for status in ['active','unknown']:
            with self.subTest(status=status):
                self.add_recent(runtime='notLoaded')
                def wake(tid, *, before_open):
                    before_open()
                    return 'owner',{'id':tid,'threadRuntimeStatus':{'type':status},'requests':[]}
                self.bridge.ipc.wake_snapshot=wake
                job=submit(self.bridge,'recent-'+status,'hello',self.project)
                if status=='active':
                    self.assertEqual(self.settled(job)['state'],'accepted')
                    self.assertEqual(self.bridge.ipc.prompts[0][0],THREAD)
                    self.journal.update(job['id'],state='completed')
                else:
                    self.assertEqual(self.settled(job)['state'],'accepted')
                    self.assertEqual(self.bridge.ipc.prompts[-1][0],THREAD)

    def test_target_project_change_blocks_borrowed_recent(self):
        self.add_recent()
        native_start=self.bridge.ipc.start
        def changed(tid,*args,**kwargs):
            self.state.write_text(json.dumps({'local-projects':{}}))
            return native_start(tid,*args,**kwargs)
        self.bridge.ipc.start=changed
        job=submit(self.bridge,'recent-create-5','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'failed')
        self.assertEqual(self.bridge.ipc.prompts,[])

    def test_failed_wake_falls_back_without_sending_to_recent(self):
        self.add_recent(runtime='notLoaded')
        def wake(tid, *, before_open):
            before_open()
            raise IPCError('load failed')
        self.bridge.ipc.wake_snapshot=wake
        job=submit(self.bridge,'recent-create-6','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertEqual(self.bridge.ipc.prompts[0][0],THREAD)

    def test_recent_search_timeout_still_searches_other_conversations(self):
        self.add_recent(runtime='notLoaded')
        clock=[0]
        def wake(tid, *, before_open):
            before_open();clock[0]=20
            raise IPCError('load timed out')
        self.bridge.ipc.wake_snapshot=wake
        with patch('carryon.creation.time.monotonic',side_effect=lambda:clock[0]):
            job=submit(self.bridge,'recent-create-7','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertEqual(self.bridge.ipc.prompts[0][0],THREAD)

    def test_newest_recent_wins_independent_of_catalog_input_order(self):
        self.add_recent(CHILD,updated_at=1)
        newest='66666666-6666-4666-8666-666666666666'
        self.add_recent(newest,updated_at=2)
        job=submit(self.bridge,'recent-create-8','hello',self.project)
        self.assertEqual(self.settled(job)['state'],'accepted')
        self.assertEqual(self.bridge.ipc.prompts[0][0],newest)
