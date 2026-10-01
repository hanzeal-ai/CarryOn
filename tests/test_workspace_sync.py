import base64
import copy
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from carryon.desktop_ipc.read_state import DesktopReadState, _hash
from carryon.desktop_ipc.ipc import IPCError
from carryon.routes.realtime import Realtime
import test_workspace
from test_workspace import T, U


def files(home, unread=(), account='account', user='user'):
    claims={'https://api.openai.com/auth':{'chatgpt_account_id':account,'user_id':user}}
    token=base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    (home/'auth.json').write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'access_token':'header.'+token+'.signature'}}))
    identity=_hash(['chatgpt',account,user])
    host='local:'+_hash(['local','local',None])
    (home/'.codex-global-state.json').write_text(json.dumps({'electron-thread-read-state-v1':{
        'version':1,'unreadByIdentity':{identity:{host:list(unread)}}}}))
    return identity


class ReadStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.identity=files(self.home,[T]);self.source=DesktopReadState(self.home)
    def tearDown(self):self.temp.cleanup()
    def test_reads_exact_identity_and_host(self):
        identity,unread,modified=self.source.capture()
        self.assertEqual(identity,self.identity);self.assertEqual(unread,{T});self.assertGreater(modified,0)
    def test_wrong_identity_host_version_or_malformed_ids_never_mean_all_read(self):
        path=self.home/'.codex-global-state.json';original=path.read_text()
        for case in ('identity','host','version','ids','missing'):
            with self.subTest(case=case):
                state=json.loads(original);data=state['electron-thread-read-state-v1']
                if case=='identity':data['unreadByIdentity']={'another':{}}
                if case=='host':data['unreadByIdentity'][self.identity]={'remote':[]}
                if case=='version':data['version']=True
                if case=='ids':data['unreadByIdentity'][self.identity]={'local:'+_hash(['local','local',None]):['not-a-thread']}
                if case=='missing':state={}
                path.write_text(json.dumps(state))
                with self.assertRaises(ValueError):self.source.capture()
    def test_identity_switch_during_capture_is_rejected(self):
        with patch.object(self.source,'identity',side_effect=[self.identity,'changed']):
            with self.assertRaisesRegex(ValueError,'账号已切换'):self.source.capture()


class SyncTests(unittest.TestCase):
    setUp=test_workspace.WorkspaceTests.setUp
    tearDown=test_workspace.WorkspaceTests.tearDown
    observe=test_workspace.WorkspaceTests.observe

    def source(self,unread=()):
        home=Path(self.temp.name);identity=files(home,unread)
        self.bridge.catalog.desktop_read_state=lambda:DesktopReadState(home)
        return identity

    def wait(self,job):
        self.workspace.sync.worker.join(5)
        self.assertFalse(self.workspace.sync.worker.is_alive())
        return self.workspace.sync.poll(job['id'])

    def test_full_sync_updates_cached_status_activity_and_missed_desktop_read(self):
        self.observe(T,request=True)
        self.observe(U,request=True)
        identity=self.source([U])
        ipc=self.bridge.ipc
        fresh=copy.deepcopy(ipc.states)
        fresh[T]['hasUnreadTurn']=False
        # CarryOn owner default false cannot clear U, which desktop says is unread.
        fresh[U]['hasUnreadTurn']=False;fresh[U]['executionBackend']='carryon-owner'
        fresh[T]['threadRuntimeStatus']={'type':'idle'}
        fresh[T]['turns'][0].update(status='completed',turnStartedAtMs=time.time()*1000,durationMs=0)
        fresh[T]['requests']=[]
        calls=[]
        def refresh(tid):calls.append(tid);ipc.states[tid]=fresh[tid];return 'owner',fresh[tid]
        ipc.refresh_snapshot=refresh
        self.bridge.realtime=Realtime(self.bridge)
        result=self.wait(self.workspace.sync.start())
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(set(calls),{T,U})
        rows={row['id']:row for row in self.workspace.projection('local')[1]}
        # Newly discovered completion remains unread; only pre-refresh notification clears.
        self.assertEqual(rows[T]['status']['state'],'idle')
        self.assertTrue(rows[U]['unread'])
        self.assertGreater(self.journal.conn.execute('SELECT sequence FROM notification_readers WHERE reader=? AND thread_id=?',('native:codex:'+identity,T)).fetchone()[0],0)
        # With no newer event, a second refresh converges after native persistence.
        files(Path(self.temp.name),[U])
        result=self.wait(self.workspace.sync.start())
        self.assertEqual(result['state'],'completed')
        rows={row['id']:row for row in self.workspace.projection('local')[1]}
        self.assertFalse(rows[T]['unread']);self.assertTrue(rows[U]['unread'])

    def test_late_discovered_desktop_read_completion_needs_no_file_rewrite(self):
        self.observe(T)
        self.source()
        path=Path(self.temp.name)/'.codex-global-state.json'
        modified=path.stat().st_mtime_ns
        ipc=self.bridge.ipc
        def refresh(tid):
            if tid==U:raise IPCError('no-client-found')
            state=copy.deepcopy(ipc.states[T])
            state['threadRuntimeStatus']={'type':'idle'}
            state['hasUnreadTurn']=False
            state['turns'][0].update(status='completed',turnStartedAtMs=(time.time()-20)*1000,durationMs=1000)
            ipc.states[T]=state
        ipc.refresh_snapshot=refresh
        for _ in range(2):
            result=self.wait(self.workspace.sync.start())
            self.assertEqual(result['state'],'completed',result)
            self.assertFalse(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])
            self.assertEqual(path.stat().st_mtime_ns,modified)

    def test_late_failed_turn_is_read_without_rewriting_desktop_file(self):
        self.observe(T)
        self.source()
        path=Path(self.temp.name)/'.codex-global-state.json';modified=path.stat().st_mtime_ns
        ipc=self.bridge.ipc
        def refresh(tid):
            if tid==U:raise IPCError('no-client-found')
            state=copy.deepcopy(ipc.states[T]);state['hasUnreadTurn']=False
            state['threadRuntimeStatus']={'type':'idle'}
            state['turns'][0].update(status='failed',turnStartedAtMs=(time.time()-20)*1000,durationMs=1000)
            ipc.states[T]=state
        ipc.refresh_snapshot=refresh
        result=self.wait(self.workspace.sync.start())
        self.assertEqual(result['state'],'completed',result)
        self.assertFalse(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])
        self.assertEqual(path.stat().st_mtime_ns,modified)

    def test_unconfirmed_old_read_state_reports_incomplete_sync(self):
        self.source()
        os.utime(Path(self.temp.name)/'.codex-global-state.json',(1,1))
        self.observe(T,request=True)
        self.bridge.ipc.refresh_snapshot=lambda tid:None
        result=self.wait(self.workspace.sync.start())
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['readPending'],1)
        self.assertTrue(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])

    def test_closed_workspace_cannot_start_or_advance_read_cursor(self):
        self.observe(T,request=True);self.source()
        ipc,generation=self.bridge.require();cutoffs=self.workspace.read_cutoffs()
        self.workspace.closed.set()
        with self.assertRaisesRegex(ValueError,'已关闭'):self.workspace.sync.start()
        with self.assertRaisesRegex(ValueError,'已关闭'):self.workspace.sync_desktop_reads(ipc,generation,cutoffs)
        self.assertEqual(self.journal.conn.execute('SELECT COUNT(*) FROM notification_readers').fetchone()[0],0)

    def test_refresh_new_message_and_old_disk_snapshot_do_not_clear_unread(self):
        self.observe(T,request=True);self.source()
        ipc,generation=self.bridge.require();cutoffs=self.workspace.read_cutoffs()
        old=self.workspace.latest_sequence(T)
        state=copy.deepcopy(ipc.states[T]);state['requests'][0]['params']['extra']='new'
        ipc.states[T]=state;self.workspace.observe(state)
        self.workspace.sync_desktop_reads(ipc,generation,cutoffs)
        self.assertTrue(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])
        path=Path(self.temp.name)/'.codex-global-state.json';os.utime(path,(1,1))
        self.workspace.sync_desktop_reads(ipc,generation,self.workspace.read_cutoffs())
        self.assertTrue(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])

    def test_account_switch_does_not_inherit_previous_native_cursor(self):
        self.observe(T,request=True);self.source()
        ipc,generation=self.bridge.require()
        self.workspace.sync_desktop_reads(ipc,generation,self.workspace.read_cutoffs())
        self.assertFalse(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])
        files(Path(self.temp.name),[T],account='other')
        self.assertTrue(next(t for t in self.workspace.projection('local')[1] if t['id']==T)['unread'])

    def test_full_directory_is_refreshed_beyond_page_and_concurrency_is_bounded(self):
        ids=[f'00000000-0000-4000-8000-{n:012d}' for n in range(130)]
        self.bridge.catalog.list=lambda *args:[{'id':tid,'title':'task','cwd':'/project'} for tid in ids]
        seen=[];lock=threading.Lock();active=0;maximum=0
        def refresh(tid):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active);seen.append(tid)
            time.sleep(.001)
            with lock:active-=1
            raise IPCError('no-client-found')
        self.bridge.ipc.refresh_snapshot=refresh
        result=self.wait(self.workspace.sync.start())
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(set(seen),set(ids));self.assertLessEqual(maximum,4)
        self.assertEqual(result['completed'],130)

    def test_poll_waits_for_snapshot_and_reports_failure(self):
        entered=threading.Event();release=threading.Event()
        def refresh(tid):entered.set();release.wait(3);raise IPCError('timeout')
        self.bridge.ipc.refresh_snapshot=refresh
        _,page=self.workspace.dispatch('local','GET','/api/activity',None,{'sync':['full']})
        job=page['sync'];self.assertTrue(entered.wait(1))
        self.assertEqual(self.workspace.sync.start()['id'],job['id'])
        _,page=self.workspace.dispatch('local','GET','/api/activity',None,{'syncId':[job['id']]})
        self.assertEqual(page['sync']['state'],'running')
        release.set();self.assertEqual(self.wait(job)['state'],'failed')

    def test_desktop_true_and_stale_connection_block_cursor_advancement(self):
        self.observe(T,request=True);self.source()
        ipc,generation=self.bridge.require();cutoffs=self.workspace.read_cutoffs()
        ipc.states[T]['hasUnreadTurn']=True
        self.workspace.sync_desktop_reads(ipc,generation,cutoffs)
        self.assertEqual(self.journal.conn.execute('SELECT COUNT(*) FROM notification_readers').fetchone()[0],0)
        self.bridge.disable()
        with self.assertRaises(Exception):self.workspace.sync_desktop_reads(ipc,generation,cutoffs)
