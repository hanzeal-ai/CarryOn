import copy
import tempfile
import unittest
from pathlib import Path
from carryon.bridge import Bridge
from carryon.store import Journal
from carryon.workspace import Workspace,project_identity
from carryon.remote_scope import scoped_dispatch
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
    def test_active_async_question_is_actionable_without_exposing_running_process(self):
        import json
        from carryon.questions import OPEN, CLOSE
        state=self.observe()
        self.assertEqual(self.workspace.dispatch('local','GET','/api/activity',None,{})[1]['threads'],[])
        state=copy.deepcopy(state)
        state['turns'][0]['items'].append({'id':'question','type':'agentMessage','phase':'commentary',
                                         'delivery':'async','text':'选择方向','questions':[{'title':'方向','options':['A','B']}]})
        self.bridge.ipc.states[T]=state;self.workspace.observe(state)
        activity=self.workspace.dispatch('local','GET','/api/activity',None,{})[1]['threads']
        self.assertEqual(len(activity),1)
        self.assertEqual(activity[0]['activityKind'],'question')
        self.assertTrue(activity[0]['needsConfirmation'])
        events=self.workspace.events('local')['events']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['kind'],'approval')
        self.workspace.observe(state)
        self.assertEqual(len(self.workspace.events('local')['events']),1)
        reply={'questionItemId':events[0]['questionId'],'question':'方向','answer':'A'}
        state=copy.deepcopy(state)
        state['turns'][0]['items'].append({'type':'userMessage','content':[{'type':'text','text':OPEN+json.dumps([reply])+CLOSE}]})
        self.bridge.ipc.states[T]=state;self.workspace.observe(state)
        self.assertEqual(self.workspace.dispatch('local','GET','/api/activity',None,{})[1]['threads'],[])

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
        all_page=self.workspace.dispatch('local','GET','/api/workspace/threads',None,{'offset':['100']})[1]
        self.assertEqual(len(all_page['threads']),25);self.assertEqual(all_page['total'],125)

    def test_projects_sort_by_latest_session_activity_before_pagination(self):
        self.observe(T, request=True)
        self.observe(U, status='completed')
        self.workspace.rows[T]['updated_at'] = 10
        self.workspace.rows[U]['updated_at'] = 20
        self.workspace.rows['older'] = {'id': 'older', 'title': 'Older', 'cwd': '/two/same', 'updated_at': 1}
        self.workspace.rows['missing'] = {'id': 'missing', 'title': 'No timestamp', 'cwd': '/zero'}
        def page(offset=0):
            return self.workspace.dispatch('local', 'GET', '/api/projects', None,
                                           {'limit': ['1'], 'offset': [str(offset)]})[1]
        self.assertEqual(page()['projects'][0]['cwd'], '/two/same')
        self.assertEqual(page()['projects'][0]['total'], 2)
        self.assertEqual(page(1)['projects'][0]['cwd'], '/one/same')
        self.assertEqual(page(2)['projects'][0]['cwd'], '/zero')
        self.assertEqual(page()['total'], 3)
        self.workspace.rows[T]['updated_at'] = 30
        self.assertEqual(page()['projects'][0]['cwd'], '/one/same')

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
        self.assertEqual(scoped_dispatch(self.bridge,'GET','/api/activity',None,False,'a')[1]['total'],0)
        self.assertEqual(len(self.workspace.events('binding:a')['events']),1)

    def test_all_sessions_sort_page_search_and_keep_live_status(self):
        from carryon.api import dispatch
        self.observe(T);self.observe(U,status='completed')
        self.workspace.rows[T]['updated_at']=10
        self.workspace.rows[U]['updated_at']=20
        self.workspace.rows[U]['projectless']=True
        self.workspace.preferences('binding:a',dict.fromkeys(('message','done','failed','approval'),False))
        route='/api/workspace/threads'
        status,first=scoped_dispatch(self.bridge,'GET',route+'?limit=1',None,False,'a')
        self.assertEqual(status,200)
        self.assertEqual(first['total'],2)
        self.assertEqual(first['nextOffset'],1)
        self.assertEqual(first['threads'][0]['id'],U)
        second=dispatch(self.bridge,'GET',route+'?limit=1&offset=1')[1]
        self.assertEqual(second['threads'][0]['id'],T)
        self.assertEqual(second['threads'][0]['status']['state'],'running')
        running=scoped_dispatch(self.bridge,'GET',route+'?filter=running',None,False,'a')[1]
        self.assertEqual([t['id'] for t in running['threads']],[T])
        searched=dispatch(self.bridge,'GET',route+'?search=Second')[1]
        self.assertEqual([t['id'] for t in searched['threads']],[U])
        self.workspace.rows[T]['updated_at']=20
        tied=dispatch(self.bridge,'GET',route)[1]
        self.assertEqual([t['id'] for t in tied['threads']],sorted([T,U],reverse=True))
        self.bridge.ipc.states={}
        self.assertTrue(all(t['status']['state']=='unknown' for t in dispatch(self.bridge,'GET',route)[1]['threads']))
        self.assertEqual(scoped_dispatch(self.bridge,'POST',route,{},False,'a')[0],404)

    def test_conversation_badge_excludes_current_thread_and_tracks_read_and_preferences(self):
        self.observe(T);self.observe(T,status='completed')
        self.observe(U,request=True)
        def summary(current=T):
            return self.workspace.dispatch('local','GET','/api/activity',None,{'limit':['1'],'currentThreadId':[current]})[1]
        result=summary()
        self.assertEqual(result['total'],2)
        self.assertTrue(result['currentThreadIncluded'])
        # Membership is checked across the full result, not just the first page.
        self.assertTrue(summary(U)['currentThreadIncluded'])
        other=self.workspace.dispatch('local','GET','/api/activity',None,{'excludeThreadId':[T]})[1]
        self.assertEqual(other['total'],1)
        self.assertEqual([t['id'] for t in other['threads']],[U])
        self.workspace.read('local',T,self.workspace.latest_sequence(T))
        self.assertFalse(summary()['currentThreadIncluded'])
        self.assertEqual(summary()['total'],1)
        self.workspace.read('local',U,self.workspace.latest_sequence(U))
        self.assertEqual(summary()['total'],1)  # Reading does not approve a request.
        self.workspace.preferences('local',{'message':True,'done':True,'failed':True,'approval':False})
        self.assertEqual(summary()['total'],0)
        self.workspace.preferences('local',dict.fromkeys(('message','done','failed','approval'),True))
        self.observe(U,status='inProgress',request=False)
        self.assertEqual(summary()['total'],0)

    def test_push_snapshot_uses_preferences_dedup_and_read_cursors(self):
        self.observe();self.observe(status='completed')
        self.assertEqual(self.workspace.push_snapshot('local')['events'],[])  # Initial registration establishes baseline.
        packet=self.workspace.push_snapshot('local',0)
        self.assertEqual([e['kind'] for e in packet['events']],['done'])
        self.assertEqual(packet['badge'],1)
        self.assertEqual(packet['nextSequence'],2)
        self.workspace.preferences('local',{'message':True,'done':False,'failed':True,'approval':True})
        self.assertEqual([e['kind'] for e in self.workspace.push_snapshot('local',0)['events']],['message'])
        self.workspace.read('local',T,2)
        self.assertEqual(self.workspace.push_snapshot('local',0)['events'],[])
        self.assertEqual(self.workspace.push_snapshot('local',0)['badge'],0)
        self.assertEqual(self.workspace.push_snapshot('binding:other',0)['badge'],1)

    def test_push_snapshot_retries_when_event_arrives_after_projection(self):
        from unittest.mock import patch
        self.observe()
        original=self.workspace.projection
        calls=[]
        def interleaved(reader):
            result=original(reader);calls.append(reader)
            if len(calls)==1:self.observe(status='completed')
            return result
        with patch.object(self.workspace,'projection',side_effect=interleaved):
            packet=self.workspace.push_snapshot('local',0)
        self.assertEqual(len(calls),2)
        self.assertEqual([e['kind'] for e in packet['events']],['done'])
        self.assertEqual(packet['nextSequence'],2)
        self.assertEqual(packet['badge'],1)

    def activity(self, reader='local', **query):
        return self.workspace.dispatch(reader,'GET','/api/activity',None,query)[1]

    def test_read_activity_retained_cleared_per_reader_and_new_events_return(self):
        self.observe();state=self.observe(status='completed')
        sequence=self.workspace.latest_sequence(T)
        self.workspace.read('local',T,sequence)
        retained=self.activity(includeRead=['true'])
        self.assertEqual(retained['total'],1)
        self.assertTrue(retained['threads'][0]['activityRead'])
        self.assertEqual(retained['threads'][0]['projectName'],'same')
        self.assertEqual(self.activity()['total'],0)  # Read history is not a badge.
        self.workspace.clear_read('local')
        self.assertEqual(self.activity(includeRead=['true'])['total'],0)
        self.assertEqual(self.activity('binding:other',includeRead=['true'])['total'],1)
        self.assertEqual(len(self.workspace.events('local')['events']),2)
        self.assertIn(T,self.workspace.thread_ids())
        restored=Workspace(self.bridge);restored.catalog_refresh()
        self.assertEqual(restored.dispatch('local','GET','/api/activity',None,{'includeRead':['true']})[1]['total'],0)
        state=copy.deepcopy(state)
        state['turns'].append({'turnId':'turn-2','status':'completed','items':[]})
        self.bridge.ipc.states[T]=state;self.workspace.observe(state)
        self.workspace.clear_read('local')  # An unread event must survive a clear race.
        result=self.activity(includeRead=['true'])
        self.assertEqual(result['total'],1)
        self.assertFalse(result['threads'][0]['activityRead'])

    def test_native_read_clear_and_readonly_remote_clear(self):
        self.observe();self.observe(status='completed')
        self.native_read_event()
        self.assertTrue(self.activity('binding:a',includeRead=['true'])['threads'][0]['activityRead'])
        code,_=scoped_dispatch(self.bridge,'POST','/api/notifications/clear-read',{},False,'a',activity_owner='alice')
        self.assertEqual(code,200)
        self.assertEqual(scoped_dispatch(self.bridge,'GET','/api/activity?includeRead=true',None,False,'a',activity_owner='alice')[1]['total'],0)
        self.assertEqual(self.activity('binding:b',includeRead=['true'])['total'],1)

    def test_clear_read_pending_activity_does_not_answer_request(self):
        self.observe(request=True)
        self.workspace.read('local',T,self.workspace.latest_sequence(T))
        self.workspace.clear_read('local')
        self.assertEqual(self.activity(includeRead=['true'])['total'],0)
        self.assertTrue(self.bridge.ipc.states[T]['requests'])
        self.assertEqual(self.activity()['total'],1)  # Pending actions remain independently counted.

    def test_accounts_on_same_binding_clear_independently(self):
        self.observe();self.observe(status='completed');self.native_read_event()
        def call(owner,method='GET',path='/api/activity?includeRead=true',body=None):
            return scoped_dispatch(self.bridge,method,path,body,False,'shared',activity_owner=owner)[1]
        self.assertEqual(call('alice')['total'],1)
        call('alice','POST','/api/notifications/clear-read',{'activityOwner':'bob'})
        self.assertEqual(call('alice')['total'],0)
        self.assertEqual(call('bob')['total'],1)
        from carryon.errors import BridgeError
        with self.assertRaises(BridgeError):
            scoped_dispatch(self.bridge,'POST','/api/notifications/clear-read',{},False,'shared')

    def test_completion_uses_native_time_not_catalog_update(self):
        from carryon.timeline import project_turn,completion_time
        self.observe()
        state=self.observe(status='completed')
        turn=state['turns'][0];turn.update(turnStartedAtMs=1700000000000,durationMs=42000)
        self.assertEqual(project_turn(turn,0)[0][0]['data']['completedAt'],1700000042)
        self.assertEqual(self.activity()['threads'][0]['completedAt'],1700000042)
        self.assertIsNone(completion_time({**turn,'status':'inProgress'}))
        self.assertIsNone(completion_time({'status':'completed','durationMs':42}))

    def test_activity_includes_each_enabled_notification_kind(self):
        for kind in ('message','done','failed','approval'):
            with self.subTest(kind=kind):
                reader='binding:'+kind
                self.workspace.preferences(reader,{k:k==kind for k in ('message','done','failed','approval')})
                self.observe()
                if kind=='approval':self.observe(request=True)
                else:self.observe(status='failed' if kind=='failed' else 'completed')
                result=self.activity(reader,limit=['1'])
                self.assertEqual(result['total'],1)
                self.assertEqual([t['id'] for t in result['threads']],[T])
                self.assertTrue(result['threads'][0]['unread'])
                self.workspace.read(reader,T,self.workspace.latest_sequence(T))
                self.assertEqual(self.activity(reader)['total'],int(kind in ('failed','approval')))
                self.workspace.preferences(reader,dict.fromkeys(('message','done','failed','approval'),False))
                self.assertEqual(self.activity(reader)['total'],0)

    def test_activity_preferences_refresh_persist_and_do_not_delete_unread(self):
        self.observe();self.observe(status='completed')
        self.assertEqual(self.activity()['total'],1)  # done + message merge into one row.
        revision=self.workspace.revision;event_revision=self.bridge.event_revision
        muted=dict.fromkeys(('message','done','failed','approval'),False)
        self.workspace.preferences('local',muted)
        self.assertGreater(self.workspace.revision,revision)
        self.assertGreater(self.bridge.event_revision,event_revision)
        self.assertEqual(self.activity()['total'],0)
        self.assertEqual(self.activity('binding:other')['total'],1)
        self.assertTrue(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])
        self.assertEqual(len(self.workspace.events('local')['events']),2)
        restored=Workspace(self.bridge);restored.catalog_refresh()
        self.assertEqual(restored.dispatch('local','GET','/api/activity',None,{})[1]['total'],0)
        self.workspace.preferences('local',{**muted,'done':True})
        self.assertEqual(self.activity()['total'],1)

    def test_activity_read_cursor_preserves_later_events_and_native_read_clears(self):
        self.observe();state=self.observe(status='completed')
        first=self.workspace.latest_sequence(T)
        state=copy.deepcopy(state)
        state['turns'].append({'turnId':'turn-2','status':'completed','items':[]})
        self.bridge.ipc.states[T]=state;self.workspace.observe(state)
        self.workspace.read('local',T,first)
        self.assertEqual(self.activity()['total'],1)
        self.native_read_event()
        self.assertEqual(self.activity()['total'],0)
        self.assertEqual(self.activity('binding:other')['total'],0)

    def test_activity_excludes_initial_completed_history_but_keeps_unloaded_notifications(self):
        self.observe(status='completed')
        self.assertEqual(self.activity()['total'],0)
        self.observe(U);self.observe(U,status='completed')
        self.bridge.ipc.states={}
        self.assertEqual([t['id'] for t in self.activity()['threads']],[U])

    def test_activity_hides_running_threads_and_respects_enabled_notifications(self):
        self.observe();self.observe(status='completed')
        self.assertEqual(self.activity(includeRead=['true'])['total'],1)
        self.observe(status='inProgress')
        self.assertEqual(self.activity(includeRead=['true'])['total'],0)
        self.assertEqual(self.activity()['total'],0)
        self.assertEqual(len(self.workspace.events('local')['events']),2)
        self.observe(status='completed')
        self.assertEqual(self.activity(includeRead=['true'])['total'],1)
        self.workspace.preferences('local',dict.fromkeys(('message','done','failed','approval'),False))
        self.assertEqual(self.activity(includeRead=['true'])['total'],0)
        self.workspace.preferences('local',{'message':False,'done':True,'failed':False,'approval':False})
        self.assertEqual(self.activity(includeRead=['true'])['total'],1)

    def test_projectless_threads_share_recent_group_and_preserve_working_directories(self):
        self.workspace.rows[T]['projectless'] = True
        self.workspace.rows[U]['projectless'] = True
        groups, threads = self.workspace.projection('local')
        self.assertEqual(len(groups), 1)
        recent = groups[0]
        self.assertEqual((recent['name'], recent['cwd'], recent['total']), ('最近', '', 2))
        self.assertEqual({t['cwd'] for t in threads}, {'/one/same', '/two/same'})
        result = self.workspace.dispatch('local', 'GET', '/api/projects/' + recent['id'] + '/threads', None, {})[1]
        self.assertEqual({t['id'] for t in result['threads']}, {T, U})
        self.observe(request=True)
        event = self.workspace.events('local')['events'][0]
        self.assertEqual(event['projectId'], recent['id'])
        self.workspace.rows[U]['projectless'] = False
        groups, _ = self.workspace.projection('local')
        self.assertEqual({g['name'] for g in groups}, {'最近', 'same'})

    def native_read_event(self, **overrides):
        import threading
        from carryon.events import Events
        ipc=self.bridge.ipc
        if not hasattr(ipc,'events'):
            ipc.lock=threading.RLock();ipc.following={};ipc.events=Events(ipc)
        packet={'type':'broadcast','method':'thread-read-state-changed','version':2,
                'sourceClientId':'desktop','params':{'hostId':'local','conversationId':T,'hasUnreadTurn':False}}
        packet.update(overrides)
        ipc.events.handle(packet)

    def test_native_read_clears_all_readers_and_survives_restart(self):
        self.observe(request=True)
        revision=self.workspace.revision;event_revision=self.bridge.event_revision
        self.native_read_event()
        self.assertGreater(self.workspace.revision,revision)
        self.assertGreater(self.bridge.event_revision,event_revision)
        for reader in ('local','binding:a','binding:b','binding:new'):
            groups,threads=self.workspace.projection(reader)
            self.assertFalse(next(t for t in threads if t['id']==T)['unread'])
            self.assertEqual(sum(g['waiting'] for g in groups),1)
        restored=Workspace(self.bridge);restored.catalog_refresh()
        self.assertFalse(next(t for t in restored.projection('binding:new')[1] if t['id']==T)['unread'])
        revision=self.workspace.revision
        self.native_read_event()
        self.assertEqual(self.workspace.revision,revision)

    def test_native_read_projects_pending_completion_but_preserves_later_message(self):
        state=self.observe()
        completed=copy.deepcopy(state);completed['turns'][0]['status']='completed'
        completed['threadRuntimeStatus']={'type':'idle'}
        # IPC has received completion, workspace observer has not processed it yet.
        self.bridge.ipc.states[T]=completed
        self.native_read_event()
        self.assertEqual(len(self.workspace.events('local')['events']),2)
        self.assertFalse(next(t for t in self.workspace.projection('binding:a')[1] if t['id']==T)['unread'])
        later=copy.deepcopy(completed);later['turns'].append({'turnId':'turn-2','status':'completed',
            'items':[{'id':'message-2','type':'agentMessage','text':'new message'}]})
        self.bridge.ipc.states[T]=later;self.workspace.observe(later)
        self.assertTrue(next(t for t in self.workspace.projection('binding:a')[1] if t['id']==T)['unread'])
        self.assertFalse(self.bridge.ipc.events.flags[T]['hasUnreadTurn'])
        self.workspace.observe(later)  # Cached native false does not consume the new message.
        self.assertTrue(next(t for t in self.workspace.projection('binding:a')[1] if t['id']==T)['unread'])

    def test_native_read_ignores_invalid_events_and_old_connection(self):
        self.observe(request=True)
        for overrides in ({'version':1},{'sourceClientId':''},
                {'params':{'hostId':'remote','conversationId':T,'hasUnreadTurn':False}},
                {'params':{'hostId':'local','conversationId':T,'hasUnreadTurn':'false'}},
                {'params':{'hostId':'local','conversationId':T,'hasUnreadTurn':True}}):
            self.native_read_event(**overrides)
            self.assertTrue(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])
        previous=self.bridge.ipc
        self.bridge.disable();self.bridge.enable()
        previous.on_read(T)
        self.assertEqual(self.workspace.latest_sequence(T),1)
        self.assertIsNone(self.journal.conn.execute("SELECT sequence FROM notification_readers WHERE reader='native:codex'").fetchone())

    def test_native_read_is_thread_scoped_and_preserves_newer_reader_cursor(self):
        self.observe(request=True);self.observe(U,request=True)
        self.native_read_event()
        threads={t['id']:t for t in self.workspace.projection('binding:a')[1]}
        self.assertFalse(threads[T]['unread']);self.assertTrue(threads[U]['unread'])
        state=copy.deepcopy(self.bridge.ipc.states[T]);state['requests'][0]['params']['extra']='later'
        self.bridge.ipc.states[T]=state;self.workspace.observe(state)
        self.workspace.read('binding:a',T,self.workspace.latest_sequence(T))
        self.assertFalse(next(t for t in self.workspace.projection('binding:a')[1] if t['id']==T)['unread'])
        self.assertTrue(next(t for t in self.workspace.projection('binding:b')[1] if t['id']==T)['unread'])
