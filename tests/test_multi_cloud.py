"""Many-to-many binding using isolated HTTP/WS consoles and a fake native IPC."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from carryon.bridge import Bridge
from carryon.cloud import CloudConnector
from carryon.cloud_manager import CloudManager
from carryon.console import ConsoleServer
from carryon.errors import BridgeError
from carryon.pairing import LocalLink
from carryon.paths import save_json
from carryon.remote_scope import scoped_dispatch, project_packet, request_key
from carryon.store import Journal
from test_cloud import Catalog, IPC, T


def wait(predicate):
    deadline=time.monotonic()+6
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.02)
    raise AssertionError('Timed out')


class MultiCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.servers=[];self.managers=[];self.bridges=[];self.journals=[]
        for index in range(2):
            server=ConsoleServer(('127.0.0.1',0),{'publicUrl':'http://127.0.0.1','consoleToken':'c'*40,'devices':{}},self.root/f'console-{index}')
            server.origin=server.public_url=f'http://127.0.0.1:{server.server_port}'
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            self.servers.append((server,worker))
            directory=self.root/f'local-{index}';directory.mkdir()
            journal=Journal(directory/'jobs.sqlite');bridge=Bridge('fake',Catalog(),journal,IPC)
            manager=CloudManager(bridge,directory)
            self.journals.append(journal);self.bridges.append(bridge);self.managers.append(manager)
        self.cookies={};IPC.sends=0

    def tearDown(self):
        for manager in self.managers:manager.stop()
        for bridge in self.bridges:
            bridge.disable()
            if bridge.realtime:
                for worker in bridge.realtime.workers:worker.join(3)
        for server,worker in self.servers:server.shutdown();server.server_close();worker.join(3)
        for journal in self.journals:journal.conn.close()
        self.temp.cleanup()

    def call(self,index,method,path,body=None,local=False):
        server=self.servers[index][0]
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        headers={'Content-Type':'application/json'}
        if not local:headers.update({'Origin':server.origin,'Cookie':self.cookies.get(index,'')})
        conn.request(method,path,json.dumps(body) if body is not None else None,headers)
        response=conn.getresponse();cookie=response.getheader('Set-Cookie')
        if cookie:self.cookies[index]=cookie.split(';')[0]
        status=response.status;result=json.loads(response.read());conn.close();return status,result

    def login(self,index):
        self.assertEqual(self.call(index,'POST','/console/login',{'token':'c'*40})[0],200)

    def bind(self,local,console,control=False):
        self.login(console)
        status,request=self.call(console,'POST','/console/link/start',{'name':f'电脑 {local}'},True)
        self.assertEqual(status,200)
        pending=self.call(console,'GET','/console/link/pending')[1]['requests']
        self.assertIn(request['id'],[p['id'] for p in pending]);self.assertNotIn('secret',json.dumps(pending))
        approved=self.call(console,'POST','/console/link/approve',{'id':request['id']})
        self.assertEqual(approved[0],200)
        # Retrying confirmation and credential receipt produces the same binding.
        self.assertEqual(self.call(console,'POST','/console/link/approve',{'id':request['id']})[1],approved[1])
        _,credentials=self.call(console,'POST','/console/link/poll',{'id':request['id'],'secret':request['secret']},True)
        self.assertEqual(self.call(console,'POST','/console/link/poll',{'id':request['id'],'secret':request['secret']},True)[1],credentials)
        manager=self.managers[local]
        manager.configure({'enabled':True,'url':self.servers[console][0].public_url.replace('http:','ws:')+'/device',
                           'deviceId':credentials['deviceId'],'token':credentials['token'],'devLocal':True,'control':control})
        self.bridges[local].enable()
        wait(lambda:all(b['connected'] for b in manager.status()['bindings']))
        return credentials['deviceId'],manager.status()['bindings'][-1]['id']

    def request(self,console,device,method,path,body=None):
        return self.call(console,'POST',f'/console/devices/{device}/request',{'method':method,'path':path,'body':body})

    def test_many_to_many_permissions_scoped_jobs_streams_and_revoke(self):
        device_a,binding_a=self.bind(0,0,True)
        device_b,binding_b=self.bind(0,1,False)
        device_c,_=self.bind(1,0)
        self.assertNotEqual(device_a,device_c)
        self.assertEqual(len(self.call(0,'GET','/console/session')[1]['devices']),2)
        for console,device in [(0,device_a),(1,device_b),(0,device_c)]:
            self.assertEqual(self.request(console,device,'GET','/api/threads')[0],200)
        payload={'requestId':'same-request','prompt':'hello'}
        route=f'/api/threads/{T}/messages'
        self.assertEqual(self.request(1,device_b,'POST',route,payload)[0],403)
        status,job=self.request(0,device_a,'POST',route,payload)
        self.assertEqual(status,202);self.assertEqual(job['id'],'same-request');self.assertNotIn('sourceBinding',job)
        wait(lambda:self.journals[0].get(request_key(binding_a,'same-request'))['state']=='accepted')
        self.assertEqual(self.request(0,device_a,'POST',route,payload)[0],202)
        self.assertEqual(IPC.sends,1)
        self.assertEqual(self.request(1,device_b,'GET','/api/jobs/same-request')[0],404)
        self.assertEqual(self.request(1,device_b,'GET','/api/jobs')[1],{'jobs':[]})
        stream=self.call(1,'POST',f'/console/devices/{device_b}/streams',{'threadId':T})[1]['streamId']
        wait(lambda:self.call(1,'GET',f'/console/devices/{device_b}/streams/{stream}?after=-1')[1]['body'] is not None)
        packet=self.call(1,'GET',f'/console/devices/{device_b}/streams/{stream}?after=-1')[1]['body']
        self.assertEqual(packet['jobs'],[])
        self.call(1,'DELETE',f'/console/devices/{device_b}/streams/{stream}')
        self.journals[0].update(request_key(binding_a,'same-request'),state='completed')
        self.managers[0].set_control(True,binding_b)
        wait(lambda:all(b['connected'] for b in self.managers[0].status()['bindings']))
        self.assertEqual(self.request(1,device_b,'POST',route,payload)[0],202)
        wait(lambda:IPC.sends==2)
        self.assertEqual(len(self.journals[0].list()),2)
        self.assertEqual(self.call(0,'DELETE',f'/console/devices/{device_a}')[0],200)
        wait(lambda:not self.managers[0].connections[binding_a].status()['connected'])
        self.assertEqual(self.request(0,device_a,'GET','/api/threads')[0],403)
        self.assertEqual(self.request(1,device_b,'GET','/api/threads')[0],200)
        self.assertEqual(self.request(0,device_c,'GET','/api/threads')[0],200)
        self.managers[0].configure({'enabled':False,'id':binding_a})
        self.assertEqual([b['id'] for b in self.managers[0].status()['bindings']],[binding_b])
        self.assertTrue(self.managers[0].connections[binding_b].status()['connected'])
        records=json.loads((self.root/'console-0/devices.json').read_text())
        self.assertNotIn(device_a,records);self.assertIn(device_c,records)
        restored=CloudManager(self.bridges[0],self.root/'local-0')
        self.assertEqual(restored.status()['bindings'][0]['id'],binding_b)
        self.assertTrue(restored.status()['bindings'][0]['control'])

    def test_cloud_revoke_invalidates_delivered_but_unsent_request(self):
        device,binding=self.bind(0,0,True)
        registered=threading.Event();release=threading.Event();original=IPC.snapshot
        def blocked(ipc,tid):registered.set();release.wait(5);return original(ipc,tid)
        try:
            with patch.object(IPC,'snapshot',blocked):
                status,_=self.request(0,device,'POST',f'/api/threads/{T}/messages',{'requestId':'cloud-revoke-pending','prompt':'hello'})
                self.assertEqual(status,202);self.assertTrue(registered.wait(2))
                status,result=self.call(0,'DELETE',f'/console/devices/{device}')
                self.assertEqual(status,200);self.assertIn('在途',result['notice'])
                wait(lambda:not self.managers[0].connections[binding].status()['connected'])
                release.set()
                wait(lambda:self.journals[0].get(request_key(binding,'cloud-revoke-pending'))['state']=='failed')
                self.assertEqual(IPC.sends,0)
        finally:release.set()

    def test_approval_auth_rejection_and_registry_restart(self):
        status,r=self.call(0,'POST','/console/link/start',{'name':'my laptop'},True)
        self.assertEqual(status,200)
        self.assertEqual(self.call(0,'GET','/console/link/pending')[0],401)
        self.assertEqual(self.call(0,'POST','/console/link/approve',{'id':r['id']})[0],401)
        self.login(0)
        self.assertEqual(self.call(0,'POST','/console/link/reject',{'id':r['id']})[0],200)
        self.assertEqual(self.call(0,'POST','/console/link/approve',{'id':r['id']})[0],400)
        self.assertEqual(self.call(0,'POST','/console/link/poll',{'id':r['id'],'secret':r['secret']},True)[0],403)
        self.assertEqual(self.call(0,'GET','/console/link/pending')[1]['requests'],[])
        device,_=self.bind(0,0)
        server=ConsoleServer(('127.0.0.1',0),{'publicUrl':'http://127.0.0.1','consoleToken':'c'*40,'devices':{}},self.root/'console-0')
        try:self.assertIn(device,server.config['devices'])
        finally:server.server_close()

    def test_background_binding_without_local_browser_poll(self):
        self.login(0)
        link=LocalLink(self.managers[0],self.bridges[0],background=True)
        def transport(url,action,body):
            status,result=self.call(0,'POST','/console/link/'+action,body,True)
            if status!=200:raise ValueError(str(result))
            return result
        # TLS itself is covered by test_cloud_tls. The credential flow uses real HTTP.
        with patch.object(link,'request',side_effect=transport), patch('carryon.pairing.LocalLink.poll', wraps=link.poll):
            # Use a mocked configure to avoid treating loopback HTTP as production WSS.
            with patch.object(self.managers[0],'configure',return_value={'enabled':True}) as configure:
                request=link.start('https://console.test',False)
                self.call(0,'POST','/console/link/approve',{'id':request['id']})
                wait(lambda:configure.called)
                self.assertFalse(configure.call_args.args[0]['control'])
                self.assertEqual(configure.call_args.args[0]['url'],'wss://console.test/device')
            link.close()


class ManagerUnitTests(unittest.TestCase):
    def test_legacy_migration_duplicate_and_targeted_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'enabled':True,'url':'wss://one.test/device','deviceId':'old','token':'x'*40,'control':True}
            path=Path(directory)/'cloud.json';save_json(path,config)
            manager=CloudManager(Mock(),directory)
            self.assertEqual(json.loads((Path(directory)/'cloud-v1-backup.json').read_text()),config)
            first=manager.status()['bindings'][0]['id']
            self.assertEqual(manager.connections[first].config,config)
            with self.assertRaises(ValueError):manager.configure(config)
            with patch.object(CloudConnector,'start'),patch.object(CloudConnector,'stop'):
                manager.configure({**config,'url':'wss://two.test/device','control':False})
                with self.assertRaises(ValueError):manager.configure({'enabled':False})
                with self.assertRaises(ValueError):manager.set_control(False)
                manager.configure({'enabled':False,'id':first})
            self.assertEqual(len(manager.status()['bindings']),1)
            self.assertNotIn('token',json.dumps(manager.status()).lower())
            self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_simultaneous_cloud_requests_share_native_send_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(Path(directory)/'jobs.sqlite');bridge=Bridge('fake',Catalog(),journal,IPC);bridge.enable()
            gate=threading.Barrier(3);results=[];IPC.sends=0
            def submit(binding):
                gate.wait()
                try:results.append(scoped_dispatch(bridge,'POST',f'/api/threads/{T}/messages',{'requestId':'same-request','prompt':'hello'},True,binding)[0])
                except BridgeError as exc:results.append(exc.status)
            workers=[threading.Thread(target=submit,args=(binding,)) for binding in ('cloud-a','cloud-b')]
            try:
                for worker in workers:worker.start()
                gate.wait()
                for worker in workers:worker.join(3)
                self.assertEqual(sorted(results),[202,409])
                wait(lambda:IPC.sends==1)
                self.assertEqual(len(journal.list()),1)
            finally:bridge.disable();journal.conn.close()

    def test_binding_survives_unavailable_codex(self):
        cloud=Mock();cloud.validate=CloudConnector.validate
        bridge=Mock();bridge.enable.side_effect=OSError('Codex closed')
        link=LocalLink(cloud,bridge)
        with patch.object(link,'request',side_effect=[{'id':'request-123','secret':'s'*40,'verification':'ABC123'},{'deviceId':'new-device','token':'t'*40}]):
            request=link.start('https://console.test',False)
            result=link.poll(request['id'])
        self.assertFalse(result['pending']);self.assertFalse(result['bridgeEnabled'])
        cloud.configure.assert_called_once()

    def test_new_console_config_starts_without_predefined_devices(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'gateway.json'
            result=subprocess.run([sys.executable,'-m','carryon.console','configure','--config',str(config),'--public-url','https://console.test'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads(config.read_text());self.assertEqual(data['devices'],{})
            self.assertNotIn(data['consoleToken'],result.stdout+result.stderr)
            self.assertEqual(config.stat().st_mode&0o777,0o600)

    def test_revocation_blocks_native_send_after_job_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(Path(directory)/'jobs.sqlite')
            bridge=Bridge('fake',Catalog(),journal,IPC);bridge.enable()
            cancelled=threading.Event();registered=threading.Event();release=threading.Event()
            original=IPC.snapshot
            def blocked(ipc,tid):registered.set();release.wait(3);return original(ipc,tid)
            def authorize():
                if cancelled.is_set():raise BridgeError('binding revoked',403)
            try:
                with patch.object(IPC,'snapshot',blocked):
                    status,job=scoped_dispatch(bridge,'POST',f'/api/threads/{T}/messages',{'requestId':'cancel-before-send','prompt':'hello'},True,'binding',authorize)
                    self.assertEqual(status,202);self.assertTrue(registered.wait(2))
                    cancelled.set();release.set()
                    wait(lambda:journal.get(request_key('binding','cancel-before-send'))['state']=='failed')
            finally:release.set();bridge.disable();journal.conn.close()
