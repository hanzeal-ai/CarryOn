import json
import tempfile
import time
import unittest
from pathlib import Path

from carryon.bridge import Bridge
from carryon.catalog import Catalog
from carryon.creation import submit, resolve_project
from carryon.errors import BridgeError
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
    def snapshot(self, tid):return 'owner',self.states[tid]
    sidebar_snapshot=snapshot
    def start(self, tid, prompt, owner, message_id, before_send):
        before_send(lambda:self.prompts.append((tid,prompt)))
        return {'id':'turn-1'}

class ProjectCreationTests(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(self.bridge.refresh_job(job['id'])['createdThreadId'],CHILD)
    def test_queued_worktree_id_requires_native_binding(self):
        catalog=Catalog(self.home)
        with self.assertRaises(ValueError):catalog.created_thread_id({'clientThreadId':THREAD})
        self.state.write_text(json.dumps({'electron-persisted-atom-state':{'client-thread-bindings-v1':{THREAD:CHILD}}}))
        self.assertEqual(catalog.created_thread_id({'clientThreadId':THREAD}),CHILD)
