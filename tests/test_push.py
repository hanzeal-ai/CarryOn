import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from carryon.push import PushService
from carryon.apns import APNsError

INSTALL='11111111-1111-4111-8111-111111111111'
THREAD='22222222-2222-4222-8222-222222222222'

class Sender:
    def __init__(self):self.sent=[];self.error=None
    def send(self,*args):
        if self.error:raise self.error
        self.sent.append(args)
    def close(self):pass

class Device:
    closed=False
    def __init__(self):self.packet={'events':[],'badge':0,'nextSequence':0};self.calls=[]
    def call(self,request,timeout):
        self.calls.append(request)
        return {'status':200,'body':copy.deepcopy(self.packet)}

class PushTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.sender=Sender();self.device=Device()
        self.server=SimpleNamespace(auth=SimpleNamespace(fingerprint='authority-a'),lock=threading.RLock(),auth_lock=threading.RLock(),sessions={k:time.monotonic()+3600 for k in ('session','new-session','s')},public_url='https://example.com',config={'devices':{'mac':{'members':{'owner':['view']},'ownerUserId':'owner'}}},devices={'mac':self.device})
        self.push=PushService(self.server,Path(self.temp.name)/'push.sqlite',self.sender)
        self.push.stop.set();self.push.worker.join();self.push.stop.clear()  # deterministic tick
        self.registration={'installationId':INSTALL,'token':'ab'*32,'environment':'sandbox','deviceId':'mac','revision':1}
    def tearDown(self):self.push.close();self.temp.cleanup()
    def register(self):self.push.register(self.registration,'session')
    def event(self):
        self.device.packet={'badge':1,'nextSequence':2,'events':[{'sequence':1,'eventId':'event1','kind':'done','threadId':THREAD,'title':'Task'}]}
    def test_notification_carries_bounded_native_anchor_without_message_content(self):
        self.register();self.event()
        self.device.packet['events'][0].update(turnId='turn-old',itemId='answer',requestId='x'*201,text='private body')
        self.push.tick()
        payload=self.sender.sent[-1][2]
        self.assertEqual(payload['turnId'],'turn-old')
        self.assertEqual(payload['itemId'],'answer')
        self.assertNotIn('requestId',payload)
        self.assertNotIn('text',payload)

    def test_concurrent_owner_registration_is_rechecked_after_baseline(self):
        self.server.auth.identity = lambda session: 'a'
        self.server.config['devices']['mac']['members']['a'] = ['view']
        other_id = '22222222-2222-4222-8222-222222222222'
        def baseline(request, timeout):
            self.push.db.execute("INSERT INTO installations(id,token,environment,device,session,owner,generation,updated,authority) VALUES(?,?,'sandbox','mac','other','b','g',?,'authority-a')",
                                 (other_id, self.registration['token'], time.time()))
            self.push.db.commit()
            return {'status':200,'body':{'nextSequence':0}}
        self.device.call = baseline
        with self.assertRaisesRegex(PermissionError, '不属于'):
            self.register()
        self.assertEqual([(row['id'], row['owner']) for row in self.push.db.execute('SELECT id,owner FROM installations')], [(other_id, 'b')])

    def test_password_rotation_blocks_old_grant_across_restart(self):
        from carryon.console_auth import ConsoleAuth, password_record
        self.server.auth=ConsoleAuth({'account':password_record('admin','old-password-123')},self.temp.name)
        self.server.auth.identities['session']='owner'
        self.register()
        self.event()
        old_row=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.push.close()
        self.server.auth=ConsoleAuth({'account':password_record('admin','new-password-456')},self.temp.name)
        self.server.sessions={}
        self.push=PushService(self.server,Path(self.temp.name)/'push.sqlite',self.sender)
        self.push.stop.set();self.push.worker.join();self.push.stop.clear()
        self.push.tick();self.push.deliver(old_row)
        self.assertEqual(self.sender.sent,[])
        self.assertEqual(self.push.db.execute('SELECT cursor FROM installations').fetchone()[0],0)
        self.assertEqual(self.push.db.execute('SELECT revision FROM registration_versions').fetchone()[0],1)
        self.server.sessions['fresh']=time.monotonic()+3600
        self.server.auth.identities['fresh']='owner'
        result=self.push.register({**self.registration,'revision':1},'fresh')
        self.assertTrue(result['registered'])
        row=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.assertEqual(row['authority'],self.server.auth.fingerprint)
        self.assertEqual(row['cursor'],2)  # reauthorization starts at the current baseline
        self.device.packet={'badge':1,'nextSequence':3,'events':[{'sequence':3,'eventId':'new-event','kind':'done','threadId':THREAD,'title':'New task'}]}
        self.push.tick()
        self.assertEqual(self.sender.sent[-1][2]['aps']['alert']['body'],'New task')

    def test_cookie_expiry_and_same_authority_restart_keep_push(self):
        self.register();self.push.close();self.server.sessions={}
        self.push=PushService(self.server,Path(self.temp.name)/'push.sqlite',self.sender)
        self.push.stop.set();self.push.worker.join();self.push.stop.clear()
        self.event();self.push.tick()
        self.assertEqual(self.sender.sent[-1][2]['aps']['alert']['body'],'Task')

    def test_capacity_applies_to_current_authority_including_reauthorized_ids(self):
        self.register()
        with self.push.db:
            self.push.db.execute("UPDATE installations SET authority='old-authority'")
            for index in range(256):
                self.push.db.execute("INSERT INTO installations(id,token,environment,device,session,owner,generation,updated,authority) VALUES(?,?,'sandbox','mac','s','owner','g',?,'old-authority')",
                                     (f'old-{index}','cd'*32,time.time()))
        self.assertTrue(self.push.register({**self.registration,'revision':2},'session')['registered'])
        with self.push.db:
            for index in range(255):
                self.push.db.execute("INSERT INTO installations(id,token,environment,device,session,owner,generation,updated,authority) VALUES(?,?,'sandbox','mac','s','owner','g',?,?)",
                                     (f'new-{index}','ef'*32,time.time(),self.server.auth.fingerprint))
        new_id='33333333-3333-4333-8333-333333333333'
        with self.assertRaisesRegex(ValueError,'数量'):
            self.push.register({**self.registration,'installationId':new_id,'revision':3},'session')
        with self.push.db:
            self.push.db.execute("INSERT INTO installations(id,token,environment,device,session,owner,generation,updated,authority) VALUES(?,'ee','sandbox','mac','s','owner','g',?,'old-authority')",(new_id,time.time()))
        with self.assertRaisesRegex(ValueError,'数量'):
            self.push.register({**self.registration,'installationId':new_id,'revision':4},'session')

    def test_old_schema_is_rejected_without_rewriting_file(self):
        import sqlite3
        path=Path(self.temp.name)/'old.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE installations(id TEXT PRIMARY KEY)')
        before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'不是当前结构'):
            PushService(self.server,path,self.sender)
        self.assertEqual(path.read_bytes(),before)

    def test_missing_members_does_not_grant_owner_access(self):
        from carryon.console_auth import ConsoleAuth, password_record
        self.server.auth=ConsoleAuth({'account':password_record('admin','old-password-123')},self.temp.name)
        self.server.auth.identities['session']='owner'
        self.server.config['devices']['mac'].pop('members')
        with self.assertRaises(PermissionError):self.register()

    def test_cursor_survives_restart_and_no_phone_stream_is_needed(self):
        self.register();self.push.tick();self.event();self.push.tick()
        payload=self.sender.sent[-1][2]
        self.assertEqual(payload['aps']['alert']['title'],'任务已完成')
        self.assertEqual(payload['server'],'https://example.com')
        self.assertEqual(payload['threadId'],THREAD)
        self.assertEqual(self.device.calls[-1]['path'],'/api/notifications/push?after=0')
        self.push.close()
        self.push=PushService(self.server,Path(self.temp.name)/'push.sqlite',self.sender)
        self.push.stop.set();self.push.worker.join();self.push.stop.clear()
        self.device.packet={'events':[],'badge':0,'nextSequence':2}
        self.push.tick()
        self.assertTrue(self.device.calls[-1]['path'].endswith('after=2'))
        self.assertEqual(self.sender.sent[-1][2]['aps'],{'badge':0})
    def test_transient_errors_keep_cursor_and_invalid_token_is_removed(self):
        self.register();self.push.tick();self.event()
        self.sender.error=APNsError(503,'ServiceUnavailable');self.push.tick()
        row=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.assertEqual(row['cursor'],0);self.assertGreater(row['retry_at'],time.time())
        self.push.update(row,retry_at=0)
        self.sender.error=APNsError(410,'Unregistered');self.push.tick()
        self.assertEqual(self.push.db.execute('SELECT COUNT(*) FROM installations').fetchone()[0],0)
    def test_logout_revocation_and_rotation(self):
        self.register();old=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.push.register({**self.registration,'token':'cd'*32,'revision':2},'new-session')
        self.assertFalse(self.push.current(old))
        self.push.unregister_session('session')
        self.assertEqual(self.push.db.execute('SELECT COUNT(*) FROM installations').fetchone()[0],1)
        self.push.revoke('mac')
        self.assertEqual(self.push.db.execute('SELECT COUNT(*) FROM installations').fetchone()[0],0)
    def test_registration_validates_device_and_environment(self):
        for updates in ({'token':'bad'},{'environment':'custom'},{'installationId':'x'}):
            with self.assertRaises(ValueError):self.push.register({**self.registration,**updates},'s')
        with self.assertRaises(PermissionError):self.push.register({**self.registration,'deviceId':'other'},'s')

    def test_logout_during_registration_cannot_recreate_grant(self):
        original=self.device.call
        def call(*args,**kwargs):
            result=original(*args,**kwargs)
            self.server.sessions.pop('session')
            return result
        self.device.call=call
        with self.assertRaises(PermissionError):self.register()
        self.assertEqual(self.push.db.execute('SELECT COUNT(*) FROM installations').fetchone()[0],0)

    def test_late_registration_cannot_replace_newer_workspace(self):
        from concurrent.futures import ThreadPoolExecutor
        entered=threading.Event();release=threading.Event()
        original=self.device.call
        def slow(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('test timeout')
            return original(*args,**kwargs)
        self.device.call=slow
        self.server.config['devices']['new']={};self.server.devices['new']=Device()
        with ThreadPoolExecutor(max_workers=1) as pool:
            old=pool.submit(self.push.register,self.registration,'session')
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.push.register({**self.registration,'deviceId':'new','revision':2},'session')['registered'])
            finally:release.set()
            self.assertTrue(old.result(timeout=3)['superseded'])
        row=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.assertEqual(row['device'],'new');self.assertEqual(row['revision'],2)
        self.assertFalse(self.push.register(self.registration,'session')['registered'])

    def test_token_rotation_retains_unsent_cursor_and_retry_state(self):
        self.register();self.push.tick();self.event()
        row=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.push.update(row,retry_at=123,failures=2,error='temporary')
        self.push.register({**self.registration,'token':'cd'*32,'revision':2},'session')
        changed=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.assertEqual((changed['cursor'],changed['retry_at'],changed['failures'],changed['error']),(0,123,2,'temporary'))
        self.assertFalse(self.push.current(row))
        self.push.tick()
        self.assertTrue(self.device.calls[-1]['path'].endswith('after=0'))
        self.assertEqual(self.sender.sent[-1][0],'cd'*32)
        self.assertEqual(self.sender.sent[-1][2]['eventId'],'event1')

    def test_denial_tombstone_rejects_late_register(self):
        self.register()
        self.push.unregister(INSTALL,'session',3)
        self.assertTrue(self.push.register({**self.registration,'revision':2},'session')['superseded'])
        self.assertEqual(self.push.db.execute('SELECT COUNT(*) FROM installations').fetchone()[0],0)

    def test_denial_after_relogin_revokes_previous_session_grant(self):
        self.register();old=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.server.sessions.pop('session')
        self.push.unregister(INSTALL,'new-session',3)
        self.assertFalse(self.push.current(old))
        self.assertEqual(self.push.db.execute('SELECT COUNT(*) FROM installations').fetchone()[0],0)
        self.assertTrue(self.push.register({**self.registration,'revision':2},'new-session')['superseded'])
        self.event();self.push.tick()
        self.assertEqual(self.sender.sent,[])

    def test_failed_prepare_keeps_last_committed_grant_active(self):
        self.register();old=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.server.config['devices']['new']={}
        broken=Device()
        def fail(*args,**kwargs):raise TimeoutError('baseline timeout')
        broken.call=fail;self.server.devices['new']=broken
        with self.assertRaises(TimeoutError):
            self.push.register({**self.registration,'deviceId':'new','revision':2},'session')
        self.assertTrue(self.push.current(old))
        self.event();self.push.tick()
        self.assertEqual(self.sender.sent[-1][2]['eventId'],'event1')
        self.assertTrue(self.push.register(self.registration,'session')['superseded'])

    def test_same_scope_rotation_does_not_require_baseline_rpc(self):
        self.register();self.event()
        def fail(*args,**kwargs):raise TimeoutError('baseline must not be called')
        self.device.call=fail
        self.assertTrue(self.push.register({**self.registration,'token':'cd'*32,'revision':2},'session')['registered'])
        row=self.push.db.execute('SELECT * FROM installations').fetchone()
        self.assertEqual(row['cursor'],0)
        self.assertTrue(self.push.current(row))
