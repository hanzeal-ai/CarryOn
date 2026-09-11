import copy
import tempfile
import unittest
from pathlib import Path
from connectnow.bridge import Bridge
from connectnow.store import Journal
from connectnow.workspace import Workspace,project_identity
from connectnow.remote_scope import scoped_dispatch
from test_cloud import IPC,T

U='22222222-2222-4222-8222-222222222222'

class Catalog:
    def list(self,limit=100,offset=0,search=''):
        return [{'id':T,'title':'First','cwd':'/one/same'},{'id':U,'title':'Second','cwd':'/two/same'}][offset:offset+limit]
    def get(self,tid):return {'id':tid,'cwd':'/one/same'}

class Native(IPC):
    def __init__(self,path):super().__init__(path);self.states={}
    def current(self,tid):return self.states.get(tid)

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.journal=Journal(Path(self.temp.name)/'journal.sqlite')
        self.bridge=Bridge('fake',Catalog(),self.journal,Native);self.bridge.enable()
        self.workspace=Workspace(self.bridge);self.bridge.workspace=self.workspace;self.workspace.catalog_refresh()
    def tearDown(self):self.workspace.close();self.bridge.disable();self.journal.conn.close();self.temp.cleanup()
    def observe(self,tid=T,status='inProgress',request=False,text='hello'):
        state={'id':tid,'threadRuntimeStatus':{'type':'active' if status=='inProgress' else 'idle'},'turns':[{'turnId':'turn-1','status':status,'items':[{'id':'message-1','type':'agentMessage','text':text}]}],'requests':[]}
        if request:state['requests']=[{'id':1,'method':'item/tool/requestUserInput','params':{'questions':[]}}]
        self.bridge.ipc.states[tid]=state;self.workspace.observe(state);return state
    def test_native_events_deduplicate_streaming_reconnect_and_restart(self):
        self.observe(text='h');self.observe(text='he');self.observe(text='hello')
        self.assertEqual(self.workspace.events('local')['events'],[])
        state=self.observe(status='completed')
        events=self.workspace.events('local')['events'];self.assertEqual({e['kind'] for e in events},{'message','done'})
        self.workspace.observe(state);Workspace(self.bridge).observe(state)
        self.assertEqual(len(self.workspace.events('local')['events']),2)
        # Delivery-journal completion cannot fabricate native completion events.
        self.journal.insert({'id':'fake-job','fingerprint':'f','kind':'message','threadId':U,'state':'completed','created':1})
        self.assertEqual(len(self.workspace.events('local')['events']),2)
    def test_initial_history_baseline_pending_requests_and_changed_fingerprint(self):
        self.observe(status='completed');self.assertEqual(self.workspace.events('local')['events'],[])
        state=self.observe(request=True);self.assertEqual(len(self.workspace.events('local')['events']),1)
        state=copy.deepcopy(state);state['requests'][0]['params']['questions']=[{'id':'new'}]
        self.workspace.observe(state);self.assertEqual(len(self.workspace.events('local')['events']),2)
    def test_project_identity_full_counts_and_independent_actionable_read_state(self):
        self.observe(request=True);self.observe(U)
        groups,threads=self.workspace.projection('binding:a')
        self.assertEqual(len(groups),2);self.assertNotEqual(groups[0]['id'],groups[1]['id'])
        self.assertEqual(sum(g['total'] for g in groups),2);self.assertEqual(sum(g['waiting'] for g in groups),1)
        self.assertEqual(sum(g['unread'] for g in groups),1)
        seq=self.workspace.latest_sequence(T)
        self.workspace.read('binding:a',T,seq)
        groups,_=self.workspace.projection('binding:a');self.assertEqual(sum(g['unread'] for g in groups),0)
        self.assertEqual(sum(g['waiting'] for g in groups),1)
        self.assertEqual(sum(g['unread'] for g in self.workspace.projection('binding:b')[0]),1)
        revision=self.workspace.revision;self.workspace.read('binding:a',T,seq)
        self.assertEqual(self.workspace.revision,revision)
        self.bridge.ipc.states={}
        self.assertEqual(sum(g['running'] for g in self.workspace.projection('binding:a')[0]),0)
        self.assertEqual(sum(g['unknown'] for g in self.workspace.projection('binding:a')[0]),2)
    def test_aggregate_counts_do_not_depend_on_the_current_page(self):
        import uuid
        rows=[{'id':str(uuid.uuid4()),'title':str(n),'cwd':'/large/project'} for n in range(125)]
        self.bridge.catalog.list=lambda *args:rows
        self.workspace.catalog_refresh()
        project=self.workspace.dispatch('local','GET','/api/projects',None,{})[1]['projects'][0]
        self.assertEqual(project['total'],125);self.assertEqual(project['unknown'],125)
        page=self.workspace.dispatch('local','GET','/api/projects/'+project['id']+'/threads',None,{'limit':['100']})[1]
        self.assertEqual(len(page['threads']),100);self.assertEqual(page['total'],125)
        page2=self.workspace.dispatch('local','GET','/api/projects/'+project['id']+'/threads',None,{'offset':['100']})[1]
        self.assertEqual(len(page2['threads']),25);self.assertEqual(page2['total'],125)

    def test_read_cursor_is_bounded_and_does_not_clear_concurrent_events(self):
        state=self.observe(request=True);first=self.workspace.latest_sequence(T)
        state=copy.deepcopy(state);state['requests'][0]['params']['extra']='changed';self.workspace.observe(state)
        self.workspace.read('local',T,first)
        self.assertTrue(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])
        with self.assertRaises(ValueError):self.workspace.read('local',T,999999)
    def test_readonly_bindings_can_save_their_own_preferences_and_read_cursor(self):
        self.observe(request=True)
        preferences={'message':False,'done':True,'failed':True,'approval':False}
        status,result=scoped_dispatch(self.bridge,'POST','/api/notifications/preferences',preferences,False,'a')
        self.assertEqual(status,200);self.assertEqual(result['preferences'],preferences)
        self.assertTrue(scoped_dispatch(self.bridge,'GET','/api/notifications/preferences',None,False,'b')[1]['preferences']['message'])
        status,_=scoped_dispatch(self.bridge,'POST','/api/notifications/read',{'threadId':T,'sequence':self.workspace.latest_sequence(T)},False,'a')
        self.assertEqual(status,200)
        self.assertEqual(scoped_dispatch(self.bridge,'GET','/api/projects?limit=1',None,False,'a')[1]['total'],2)
        self.assertEqual(scoped_dispatch(self.bridge,'GET','/api/activity',None,False,'a')[1]['total'],1)
        self.assertEqual(len(self.workspace.events('binding:a')['events']),1)
