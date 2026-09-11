import json
import time
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from connectnow.cli import start
from unittest.mock import Mock, patch
import test_console
from connectnow.linking import LinkRequests
from connectnow.pairing import LocalLink
from connectnow.cloud import CloudConnector
from connectnow.timeline import project_item


class LinkTests(unittest.TestCase):
    def test_confirmation_secret_expiry_and_single_use(self):
        links=LinkRequests();r=links.start()
        self.assertIsNone(links.poll(r['id'],r['secret']))
        with self.assertRaises(PermissionError):links.poll(r['id'],'wrong')
        links.approve(r['id'],'device')
        with self.assertRaises(ValueError):links.approve(r['id'],'other')
        self.assertEqual(links.poll(r['id'],r['secret']),'device')
        with self.assertRaises(ValueError):links.poll(r['id'],r['secret'])
        r=links.start();links.entries[r['id']]['expires']=time.monotonic()-1
        with self.assertRaises(ValueError):links.approve(r['id'],'device')

    def test_local_permission_binding_and_replaced_request(self):
        cloud=Mock();cloud.validate=CloudConnector.validate
        bridge=Mock();local=LocalLink(cloud,bridge)
        with patch.object(local,'request',side_effect=[{'id':'first-id','secret':'s'*40,'verification':'ABC123'},
                {'id':'second-id','secret':'t'*40,'verification':'DEF456'}, {'deviceId':'my-mac','token':'d'*40}]):
            first=local.start('https://example.test/connectnow',False)
            second=local.start('https://example.test/connectnow',True)
            self.assertNotIn('secret',second);self.assertNotIn('t'*40,json.dumps(second))
            with self.assertRaises(ValueError):local.poll(first['id'])
            local.poll(second['id'])
            self.assertTrue(cloud.configure.call_args.args[0]['control'])
            self.assertEqual(cloud.configure.call_args.args[0]['url'],'wss://example.test/connectnow/device')
            bridge.enable.assert_called_once()
            with self.assertRaises(ValueError):local.poll(second['id'])

    def test_permission_toggle_preserves_binding_and_rejects_unbound(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=CloudConnector(Mock(),directory)
            with self.assertRaises(ValueError):cloud.set_control(True)
            cloud.config={'enabled':True,'url':'wss://example.test/device','deviceId':'device','token':'d'*40,'control':False}
            with patch.object(cloud,'_configure') as apply:
                cloud.set_control(True)
                self.assertEqual(apply.call_args.args[0],{**cloud.config,'control':True})
                with self.assertRaises(ValueError):cloud.set_control('true')
                self.assertEqual(apply.call_count,1)

    def test_local_start_does_not_reenable_existing_service(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(state_dir=Path(directory),port=0,codex_home=Path(directory),no_open=True)
            info={'version':'test','port':1234}
            with patch('connectnow.cli.running',return_value=info), patch('connectnow.cli.call') as call:
                self.assertEqual(start(args),0);call.assert_not_called()
            with patch('connectnow.cli.running',side_effect=[None,info]), patch('connectnow.cli.subprocess.Popen'), patch('connectnow.cli.call',side_effect=[{'enabled':True},OSError('Codex closed')]) as call:
                self.assertEqual(start(args),0)
                self.assertEqual(call.call_args.args[1:],('/bridge',{'enabled':True}))

    def test_steered_marker_is_supported_without_invented_content(self):
        item=project_item({'type':'steered','id':'s'},{'turnId':'t'},0)
        self.assertTrue(item['supported']);self.assertEqual(item['title'],'补充指令已接收')
        self.assertEqual(item['data'],{});self.assertEqual(item['text'],'')


class LinkHTTPTests(unittest.TestCase):
    setUp=test_console.ConsoleTests.setUp
    tearDown=test_console.ConsoleTests.tearDown
    call=test_console.ConsoleTests.call
    login=test_console.ConsoleTests.login

    def test_authorization_requires_cookie_origin_and_owned_device(self):
        self.assertEqual(self.call('POST','/console/link/start',{})[0],403)
        status,r,_=self.call('POST','/console/link/start',{},False)
        self.assertEqual(status,200)
        self.assertEqual(self.call('POST','/console/link/approve',{'id':r['id'],'deviceId':'my-mac'})[0],401)
        self.login()
        status,inspection,_=self.call('POST','/console/link/inspect',{'id':r['id']})
        self.assertEqual(status,200);self.assertEqual(inspection,{'verification':r['verification']})
        self.assertEqual(self.call('POST','/console/link/approve',{'id':r['id'],'deviceId':'my-mac'},'https://evil.test')[0],403)
        self.assertEqual(self.call('POST','/console/link/approve',{'id':r['id'],'deviceId':'unknown'})[0],403)
        self.assertEqual(self.call('POST','/console/link/approve',{'id':r['id'],'deviceId':'my-mac'})[0],200)
        self.assertEqual(self.call('POST','/console/link/poll',{'id':r['id'],'secret':'wrong'},False)[0],403)
        status,result,_=self.call('POST','/console/link/poll',{'id':r['id'],'secret':r['secret']},False)
        self.assertEqual(status,200);self.assertEqual(result['deviceId'],'my-mac');self.assertEqual(result['token'],'d'*40)
        self.assertEqual(self.call('POST','/console/link/poll',{'id':r['id'],'secret':r['secret']},False)[0],400)

class LinkStatusTests(unittest.TestCase):
    def test_status_tracks_pending_bound_expired_and_failure_without_secrets(self):
        cloud=Mock();cloud.validate=CloudConnector.validate
        local=LocalLink(cloud,Mock(),background=True)
        with patch.object(local,'request',side_effect=[{'id':'request-id','secret':'s'*40,'verification':'ABC123'},
                {'deviceId':'my-mac','token':'d'*40}]), patch('threading.Thread'):
            self.assertEqual(local.status(),{'state':'idle'})
            local.start('https://example.test',False)
            self.assertEqual(local.status()['state'],'pending')
            self.assertNotIn('s'*40,json.dumps(local.status()))
            local.failure='连接申请已拒绝'
            self.assertEqual(local.status()['state'],'failed')
            local.pending['expires']=time.monotonic()-1
            self.assertEqual(local.status()['state'],'failed')
            self.assertEqual(local.status()['error'],'连接申请已拒绝')
            local.failure=None
            self.assertEqual(local.status()['state'],'expired')
            local.pending['expires']=time.monotonic()+100
            local.failure=None
            local.poll('request-id')
            self.assertEqual(local.status()['state'],'bound')
            self.assertNotIn('d'*40,json.dumps(local.status()))

    def test_remote_rejection_is_visible_without_forwarding_arbitrary_error_text(self):
        import io
        import urllib.error
        for text,expected in [('连接申请已拒绝','连接申请已拒绝'),('untrusted secret text','云端连接授权失败或已过期，请重新发起连接')]:
            failure=urllib.error.HTTPError('https://example.test',400,'Bad Request',{},io.BytesIO(json.dumps({'error':text}).encode()))
            with patch('connectnow.pairing.urllib.request.build_opener') as build:
                build.return_value.open.side_effect=failure
                with self.assertRaises((PermissionError,ValueError)) as result:
                    LocalLink.request('https://example.test','poll',{})
                self.assertEqual(str(result.exception),expected)

    def test_background_rejection_remains_terminal_until_next_request(self):
        cloud=Mock();local=LocalLink(cloud,Mock())
        start={'id':'request-id','secret':'s'*40,'verification':'ABC123'}
        with patch.object(local,'request',return_value=start):local.start('https://example.test',False)
        with patch.object(local.closed,'wait',return_value=False),patch.object(local,'request',side_effect=PermissionError('连接申请已拒绝')):
            local._wait('request-id')
        local.pending['expires']=time.monotonic()-1
        self.assertEqual(local.status()['state'],'failed')
        self.assertEqual(local.status()['error'],'连接申请已拒绝')
        cloud.configure.assert_not_called()
        with patch.object(local,'request',return_value={**start,'id':'next-request'}):local.start('https://example.test',False)
        self.assertEqual(local.status()['state'],'pending')
        self.assertIsNone(local.status()['error'])

    def test_background_timeout_remains_expired(self):
        local=LocalLink(Mock(),Mock())
        with patch.object(local,'request',return_value={'id':'request-id','secret':'s'*40,'verification':'ABC123'}):
            local.start('https://example.test',False)
        local.pending['expires']=time.monotonic()-1
        with patch.object(local.closed,'wait',return_value=False):local._wait('request-id')
        self.assertEqual(local.status()['state'],'expired')
        self.assertIsNone(local.status()['error'])
