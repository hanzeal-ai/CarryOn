import tempfile
import time
import unittest
from pathlib import Path
from carryon.bridge import Bridge, BridgeError
from carryon.store import Journal
from carryon.api import dispatch
from carryon.ipc import IPCError

PARENT='11111111-1111-4111-8111-111111111111'
CHILD='22222222-2222-4222-8222-222222222222'
OTHER='33333333-3333-4333-8333-333333333333'


class Catalog:
    def get(self, tid):
        if tid==CHILD:raise ValueError('ephemeral not persisted')
        return {'id':tid}
    def side_candidates(self):return [CHILD]
    def queued(self, tid):return []


class IPC:
    def __init__(self,_):
        self.connected=False
        self.calls=[];self.before=None
        self.state={'id':CHILD,'ephemeral':True,'sideConversation':True,'forkedFromId':PARENT,
                    'title':'Side title','threadRuntimeStatus':{'type':'active'},'turns':[
                    {'turnId':'t','status':'inProgress','params':{},'items':[{'type':'agentMessage','text':'Live side text'}]}]}
    def connect(self):self.connected=True
    def close(self):self.connected=False
    def current(self,tid):return self.state if tid==CHILD else None
    def snapshot(self, tid):
        if tid != CHILD: raise IPCError('no-client-found')
        return 'side-owner', self.state
    sidebar_snapshot = snapshot
    def start(self, tid, prompt, owner, client_id, guard, **kwargs):
        if self.before: self.before()
        guard(lambda: self.calls.append(('start',tid,prompt,owner)))
        return {'id':'next-turn'}
    def request(self, method, params, version, owner, guard):
        if self.before: self.before()
        guard(lambda: self.calls.append((method, params, owner)))
        return {'result':{'ok':True}}


class SideChatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=Journal(Path(self.temp.name)/'jobs.sqlite')
        self.bridge=Bridge('socket',Catalog(),self.journal,IPC);self.bridge.enable()
    def tearDown(self):
        self.bridge.disable();self.journal.conn.close();self.temp.cleanup()
    def discover(self):self.bridge._discover_sides(self.bridge.ipc,self.bridge.generation)
    def test_verified_parent_status_and_history_without_database_row(self):
        self.discover()
        result=self.bridge.side_chats(PARENT)
        self.assertEqual(result['chats'][0]['state'],'running')
        self.assertEqual(result['chats'][0]['parentId'],PARENT)
        self.assertEqual(self.bridge.side_history(PARENT,CHILD)['messages'][0]['text'],'Live side text')
        self.assertEqual(self.bridge.side_chats(OTHER)['chats'],[])
    def test_binding_is_not_proof_of_side_chat(self):
        self.bridge.ipc.state['sideConversation']=False;self.discover()
        self.assertEqual(self.bridge.side_registry,{})
    def test_wrong_parent_and_changed_identity_rejected(self):
        self.discover()
        with self.assertRaises(ValueError):self.bridge.side_history(OTHER,CHILD)
        self.bridge.ipc.state['forkedFromId']=OTHER
        with self.assertRaises(ValueError):self.bridge.side_history(PARENT,CHILD)
    def test_revocation_clears_access_and_new_connection_forgets_registry(self):
        self.discover();self.bridge.disable()
        with self.assertRaises(BridgeError):self.bridge.side_chats(PARENT)
        with self.assertRaises(BridgeError):self.bridge.side_history(PARENT,CHILD)
        self.bridge.enable();self.assertEqual(self.bridge.side_registry,{})

    def wait_job(self, job):
        for _ in range(100):
            result=self.journal.get(job['id'])
            if result['state'] not in ('preparing','dispatching'):return result
            time.sleep(.01)
        self.fail('Job did not settle')

    def compose(self, request_id='side-compose-test', parent=PARENT, **kwargs):
        return dispatch(self.bridge,'POST',f'/api/side-chats/{CHILD}/compose',
                        {'parentId':parent,'requestId':request_id,'prompt':'hello'},**kwargs)

    def test_idle_side_uses_shared_start_without_database_row(self):
        self.discover();self.bridge.ipc.state.update(threadRuntimeStatus={'type':'idle'}, requests=[])
        self.bridge.ipc.state['turns'][0]['status']='completed'
        code,job=self.compose(remote=True,control=True)
        self.assertEqual(code,202);self.assertEqual(self.wait_job(job)['state'],'accepted')
        self.assertEqual(self.bridge.ipc.calls,[('start',CHILD,'hello','side-owner')])
        self.assertEqual(self.compose()[1]['id'],job['id'])
        self.assertEqual(len(self.bridge.ipc.calls),1)
        self.assertEqual(job['sideParentId'],PARENT)
        self.bridge.ipc.state['turns'].append({'turnId':'next-turn','status':'completed','items':[]})
        self.assertEqual(self.bridge.refresh_job(job['id'])['state'],'completed')

    def test_cloud_side_job_is_scoped_and_can_be_polled(self):
        from carryon.remote_scope import scoped_dispatch, request_key
        self.discover();self.bridge.ipc.state.update(threadRuntimeStatus={'type':'idle'}, requests=[])
        self.bridge.ipc.state['turns'][0]['status']='completed'
        route=f'/api/side-chats/{CHILD}/compose'
        body={'parentId':PARENT,'requestId':'cloud-side-request','prompt':'hello'}
        code,job=scoped_dispatch(self.bridge,'POST',route,body,True,'binding-a')
        self.assertEqual(code,202)
        self.assertEqual(job['id'],body['requestId'])
        internal=request_key('binding-a',body['requestId'])
        self.assertEqual(self.wait_job({'id':internal})['sourceBinding'],'binding-a')
        _,polled=scoped_dispatch(self.bridge,'GET','/api/jobs/'+body['requestId'],None,True,'binding-a')
        self.assertEqual(polled['id'],body['requestId'])
        self.assertNotIn('sourceBinding',polled)
        with self.assertRaises(BridgeError):
            scoped_dispatch(self.bridge,'GET','/api/jobs/'+body['requestId'],None,True,'binding-b')
        scoped_dispatch(self.bridge,'POST',route,body,True,'binding-a')
        self.assertEqual(len(self.bridge.ipc.calls),1)

    def test_running_side_steers_and_waiting_side_queues(self):
        self.discover()
        _,job=self.compose()
        self.assertEqual(self.wait_job(job)['state'],'completed')
        self.assertEqual(self.bridge.ipc.calls[-1][0],'thread-follower-steer-turn')
        self.assertEqual(self.bridge.ipc.calls[-1][1]['conversationId'],CHILD)
        self.bridge.ipc.state['requests']=[{'id':1,'method':'item/commandExecution/requestApproval','params':{}}]
        _,job=self.compose('side-queue-test')
        self.assertEqual(self.wait_job(job)['state'],'completed')
        self.assertEqual(self.bridge.ipc.calls[-1][0],'thread-follower-set-queued-follow-ups-state')
        self.assertEqual(list(self.bridge.ipc.calls[-1][1]['state']),[CHILD])

    def test_side_rejects_unverified_wrong_parent_readonly_remote_and_missing_owner(self):
        with self.assertRaises(ValueError): self.compose()
        self.discover()
        with self.assertRaises(ValueError): self.compose(parent=OTHER)
        with self.assertRaises(BridgeError): self.compose(remote=True,control=False)
        self.bridge.ipc.snapshot=lambda tid: (_ for _ in ()).throw(IPCError('no-client-found'))
        with self.assertRaises(IPCError): self.compose()
        self.assertEqual(self.bridge.ipc.calls,[])
        self.assertEqual(self.journal.list(),[])

    def test_changed_identity_and_revoked_authorization_at_write_are_rejected(self):
        self.discover()
        self.bridge.ipc.before=lambda:self.bridge.ipc.state.update(forkedFromId=OTHER)
        _,job=self.compose()
        self.assertEqual(self.wait_job(job)['state'],'failed');self.assertEqual(self.bridge.ipc.calls,[])
        self.bridge.ipc.before=None;self.bridge.ipc.state['forkedFromId']=PARENT
        checks=[]
        def authorize():
            checks.append(True)
            if len(checks)>1:raise BridgeError('revoked',403)
        _,job=self.compose('side-revoke-test',authorize=authorize)
        self.assertEqual(self.wait_job(job)['state'],'failed');self.assertEqual(self.bridge.ipc.calls,[])

    def test_interrupt_and_parent_binding_cannot_be_bypassed(self):
        self.discover()
        body={'parentId':PARENT,'requestId':'side-stop-test','action':'interrupt','expectedTurnId':'t'}
        _,job=dispatch(self.bridge,'POST',f'/api/side-chats/{CHILD}/operations',body)
        self.assertEqual(self.wait_job(job)['state'],'completed')
        self.assertEqual(self.bridge.ipc.calls[-1][0],'thread-follower-interrupt-turn')
        with self.assertRaises(ValueError): dispatch(self.bridge,'POST',f'/api/side-chats/{CHILD}/operations',{**body,'parentId':OTHER})
        with self.assertRaises(ValueError): dispatch(self.bridge,'POST',f'/api/threads/{CHILD}/compose',{'prompt':'hello','requestId':'side-bypass-test'})
