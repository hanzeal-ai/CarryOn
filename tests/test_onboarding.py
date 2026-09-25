import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_console_auth import AccountTests
from carryon.console_auth import ConsoleAuth
from carryon.onboarding import exchange
from carryon.workspace_access import capability, require


class BindingTests(AccountTests):
    def test_cancel_persistence_failures_are_retryable(self):
        cookie = self.register_user('alice')
        invite = self.server.binding_invites.start({'name':'Mac','permissions':['view']})
        ident, secret = invite['url'].split('#carryon-bind=')[1].split('.')
        poll = {'id':ident,'secret':invite['secret']}
        invites = self.server.binding_invites
        with patch.object(invites, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):invites.cancel(poll)
        self.assertEqual(invites.entries[ident]['state'], 'waiting')
        # The file sync succeeds; the directory sync fails after rename.
        with patch('carryon.binding_invites.os.fsync', side_effect=[None, OSError('directory sync failed')]):
            with self.assertRaises(OSError):invites.cancel(poll)
        self.assertEqual(invites.entries[ident]['state'], 'cancelled')
        self.assertEqual(self.request('binding/accept', {'id':ident,'secret':secret}, cookie)[0], 400)
        self.assertEqual(invites.cancel(poll)['state'], 'cancelled')

    def test_cancel_binding_invalidates_scan_and_is_retryable(self):
        cookie = self.register_user('alice')
        invite = self.server.binding_invites.start({'name':'Mac','permissions':['view']})
        ident, secret = invite['url'].split('#carryon-bind=')[1].split('.')
        poll = {'id':ident,'secret':invite['secret']}
        scan = {'id':ident,'secret':secret}
        self.assertEqual(self.request('binding/cancel', scan, origin=False)[0], 403)
        self.assertEqual(self.request('binding/cancel', poll)[0], 403)
        for _ in range(2):
            self.assertEqual(self.request('binding/cancel', poll, origin=False)[1]['state'], 'cancelled')
        self.stop(); self.start()
        self.assertEqual(self.request('binding/accept', scan, cookie)[0], 400)
        self.assertEqual(self.server.config['devices'], {})

    def test_cancel_cannot_undo_confirmed_binding(self):
        cookie = self.register_user('alice')
        invite = self.server.binding_invites.start({'name':'Mac','permissions':['view']})
        ident, secret = invite['url'].split('#carryon-bind=')[1].split('.')
        self.assertEqual(self.request('binding/accept', {'id':ident,'secret':secret}, cookie)[0], 200)
        poll = {'id':ident,'secret':invite['secret']}
        self.assertEqual(self.request('binding/cancel', poll, origin=False)[0], 400)
        self.assertEqual(self.request('binding/poll', poll, origin=False)[1]['state'], 'bound')

    def register_user(self, username):
        status, _, cookie = self.request('register', {'username':username, 'password':'a long password 123', **self.server.auth.create_registration_invite()})
        self.assertEqual(status, 200)
        return cookie

    def test_registered_accounts_cannot_see_legacy_devices_or_each_other(self):
        self.server.config['devices']['old'] = {'deviceToken':'d'*40, 'apiToken':'a'*40}
        alice = self.register_user('alice')
        bob = self.register_user('bob')
        invite = self.server.binding_invites.start({'name':'Alice Mac', 'permissions':['view','files']})
        key, secret = invite['url'].split('#carryon-bind=')[1].split('.')
        scan = {'id':key, 'secret':secret}
        self.assertEqual(self.request('binding/inspect', scan)[0], 401)
        details = self.request('binding/inspect', scan, alice)
        self.assertEqual(details[1]['account']['username'], 'alice')
        accepted = self.request('binding/accept', scan, alice)
        self.assertEqual(accepted[0], 200)
        device = accepted[1]['deviceId']
        self.assertEqual(self.request('binding/accept', scan, alice)[1]['deviceId'], device)
        self.assertEqual(self.request('binding/accept', scan, bob)[0], 403)
        self.assertEqual([d['id'] for d in self.request('session', cookie=alice)[1]['devices']], [device])
        self.assertEqual(self.request('session', cookie=bob)[1]['devices'], [])
        self.assertEqual(self.request('binding/pending', cookie=bob)[1]['requests'], [])
        self.assertEqual(self.request('devices/'+device+'/request', {'method':'GET','path':'/api/status'}, bob)[0], 403)
        self.assertEqual(self.request('devices/'+device+'/request', {'method':'POST','path':'/api/threads','body':{}}, alice)[0], 403)
        with self.assertRaises(PermissionError): self.server.binding_invites.poll(scan)
        result = self.server.binding_invites.poll({'id':key, 'secret':invite['secret']})
        self.assertEqual(result['state'], 'bound')
        self.assertNotIn('token', accepted[1])
        # Account sessions, their identities and grants survive a cloud restart.
        self.stop(); self.start()
        self.assertEqual(self.request('session', cookie=bob)[1]['devices'], [])
        self.assertEqual(self.request('session', cookie=alice)[1]['devices'][0]['id'], device)

    def test_expired_and_wrong_origin_bindings_are_rejected(self):
        cookie = self.register_user('alice')
        invitation = self.server.binding_invites.start({'name':'Mac', 'permissions':['view']})
        key, secret = invitation['url'].split('#carryon-bind=')[1].split('.')
        data = {'id':key, 'secret':secret}
        self.assertEqual(self.request('binding/accept', data, cookie, origin=False)[0], 403)
        self.server.binding_invites.entries[key]['expires'] = time.time()-1
        self.assertEqual(self.request('binding/accept', data, cookie)[0], 400)
        self.assertEqual(self.server.config['devices'], {})

    def test_member_invitation_needs_computer_confirmation_and_revocation_closes_stream(self):
        from carryon.member_management import manage
        import hashlib
        alice = self.register_user('alice'); bob = self.register_user('bob')
        aid = self.request('session',cookie=alice)[1]['account']['id']
        bid = self.request('session',cookie=bob)[1]['account']['id']
        self.server.save_devices({'mac':{'deviceToken':'d'*40,'apiToken':'a'*40,'members':{aid:['view']},'ownerUserId':aid}})
        credentials = {'deviceId':'mac','token':'d'*40}
        invite = manage(self.server, {**credentials,'action':'invite','permissions':['view']})
        key, secret = invite['url'].split('#carryon-bind=')[1].split('.')
        self.assertEqual(self.request('binding/accept',{'id':key,'secret':secret},bob)[1]['state'],'accepted')
        self.assertEqual(self.request('session',cookie=bob)[1]['devices'],[])
        decision = {**credentials,'action':'confirm','id':key,'secret':invite['secret'],'accountId':bid}
        manage(self.server, decision)
        self.assertEqual(self.request('session',cookie=bob)[1]['devices'][0]['id'],'mac')
        session_key=hashlib.sha256(bob.split('=',1)[1].encode()).hexdigest()
        self.server.console_streams['test-stream']={'device':'mac','session':session_key,'last':time.monotonic()}
        manage(self.server,{**credentials,'action':'revoke','accountId':bid})
        self.assertNotIn('test-stream',self.server.console_streams)
        with self.assertRaises(PermissionError): manage(self.server,decision)
        self.assertEqual(self.request('session',cookie=bob)[1]['devices'],[])
        for method, path in [('GET','/api/status'),('GET','/api/threads/t/artifacts/'+'a'*64),('POST','/api/threads')]:
            self.assertEqual(self.request('devices/mac/request',{'method':method,'path':path,'body':{}},bob)[0],403)

    def test_directed_binding_requires_target_phone_confirmation(self):
        alice = self.register_user('alice')
        bob = self.register_user('bob')
        invitation = self.server.binding_invites.start({'name':'Second','permissions':['view'],'targetAccount':'alice'})
        self.assertEqual(self.server.config['devices'], {})
        self.assertEqual(self.request('binding/pending',cookie=bob)[1]['requests'], [])
        pending = self.request('binding/pending',cookie=alice)[1]['requests']
        self.assertEqual(pending[0]['id'], invitation['id'])
        self.assertEqual(self.request('binding/respond', {'id':invitation['id']}, bob)[0],403)
        status, result, _ = self.request('binding/respond', {'id':invitation['id']}, alice)
        self.assertEqual(status,200)
        self.assertEqual(self.request('binding/respond', {'id':invitation['id']}, alice)[1],result)
        self.assertEqual(len(self.server.config['devices']),1)
        self.assertEqual(self.request('session',cookie=bob)[1]['devices'],[])
        self.assertEqual(self.request('session',cookie=alice)[1]['devices'][0]['id'],result['deviceId'])
        polled=self.server.binding_invites.poll({'id':invitation['id'],'secret':invitation['secret']})
        self.assertEqual(polled['deviceId'],result['deviceId'])
        self.server.revoke_device(result['deviceId'])
        self.assertEqual(self.request('binding/respond',{'id':invitation['id']},alice)[0],403)

    def test_revocation_during_forward_preserves_uncertainty_and_cleans_new_stream(self):
        from types import SimpleNamespace
        import threading
        cookie=self.register_user('alice')
        identity=self.request('session',cookie=cookie)[1]['account']['id']
        record={'deviceToken':'d'*40,'apiToken':'a'*40,'members':{identity:['view','send']}}
        self.server.save_devices({'mac':record})
        def call(message, **kwargs):
            if message['type']=='unsubscribe': return {'status':200,'body':{'closed':True}}
            self.server.config['devices']['mac']={**record,'members':{}}
            if message['type']=='subscribe':return {'status':200,'body':{'streamId':message['streamId']}}
            return {'status':202,'body':{'id':'original-request','state':'accepted'}}
        device=SimpleNamespace(lock=threading.Condition(),streams={},closed=False,call=call)
        self.server.devices['mac']=device
        status, body, _=self.request('devices/mac/request',{'method':'POST','path':'/api/threads/t/messages','body':{'requestId':'original-request','prompt':'hello'}},cookie)
        self.assertEqual(status,409);self.assertTrue(body['uncertain'])
        self.server.config['devices']['mac']=record
        status, body, _=self.request('devices/mac/streams',{'threadId':'t'},cookie)
        self.assertEqual(status,403)
        self.assertEqual(device.streams,{})
        self.assertEqual(self.server.console_streams,{})

    def test_new_members_require_confirmation_even_with_other_workspace_credentials(self):
        alice=self.register_user('alice')
        identity=self.request('session',cookie=alice)[1]['account']['id']
        self.server.save_devices({'source':{'deviceToken':'s'*40,'apiToken':'a'*40,'members':{identity:['view']}},
                                  'target':{'deviceToken':'t'*40,'apiToken':'b'*40,'members':{}}})
        from carryon.member_management import manage
        with self.assertRaises(PermissionError):
            manage(self.server, {'deviceId':'target','token':'t'*40,'action':'grant','accountId':identity,
                   'permissions':['view'], 'source':{'deviceId':'source','token':'s'*40}})
        self.assertEqual(self.server.config['devices']['target']['members'],{})

    def test_activity_owner_is_derived_from_login_not_request_body(self):
        from types import SimpleNamespace
        import threading
        cookie=self.register_user('alice')
        identity=self.request('session',cookie=cookie)[1]['account']['id']
        self.server.save_devices({'mac':{'deviceToken':'d'*40,'apiToken':'a'*40,'members':{identity:['view']}}})
        captured=[]
        def call(message,**kwargs):
            captured.append(message)
            return {'status':200,'body':{'cleared':True}}
        self.server.devices['mac']=SimpleNamespace(lock=threading.Condition(),streams={},closed=False,call=call)
        status,_,_=self.request('devices/mac/request',{'method':'POST','path':'/api/notifications/clear-read',
            'activityOwner':'forged','body':{'activityOwner':'forged'}},cookie)
        self.assertEqual(status,200)
        self.assertEqual(captured[0]['activityOwner'],identity)


class InitializationTests(unittest.TestCase):
    def test_saved_bindings_remain_visible_when_service_is_stopped(self):
        from carryon.cloud_manager import CloudManager
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            config={'enabled':True,'url':'wss://example.test/device','deviceId':'mac','token':'t'*43,'control':False}
            path=root/'cloud.json';path.write_text(json.dumps({'version':2,'bindings':{'a'*32:config}}))
            before=path.read_bytes()
            value=CloudManager.saved_status(root)
            self.assertFalse(value['connected']);self.assertTrue(value['enabled'])
            self.assertNotIn('token',json.dumps(value));self.assertEqual(path.read_bytes(),before)

    def test_bridge_reconnect_waits_for_codex_and_explicit_off_stops_retry(self):
        from carryon.lifecycle import BridgeLifecycle
        from carryon.errors import BridgeError
        import threading
        class FakeBridge:
            available=False
            enabled=False
            def status(self):return {'enabled':self.enabled}
            def disable(self):self.enabled=False
            def enable(self):
                if not self.available:raise BridgeError('Codex unavailable')
                self.enabled=True
        bridge=FakeBridge(); lifecycle=BridgeLifecycle(bridge);lifecycle.start()
        try:
            self.assertEqual(lifecycle.configure(True)['connectionState'],'waiting')
            bridge.available=True
            deadline=time.monotonic()+4
            while not lifecycle.status()['enabled'] and time.monotonic()<deadline: time.sleep(.05)
            self.assertTrue(lifecycle.status()['enabled'])
            lifecycle.configure(False)
            self.assertEqual(lifecycle.status()['connectionState'],'stopped')
            self.assertFalse(lifecycle.requested)
        finally:lifecycle.close()

    def test_no_auto_start_binding_is_resumable_and_does_not_launch_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); directory = root/'workspace'
            invitation = {'id':'a'*32, 'secret':'b'*43, 'url':'https://example.test/#carryon-bind='+'a'*32+'.'+'c'*43, 'expiresAt':time.time()+300}
            result = {'state':'bound','deviceId':'mac','token':'t'*43,'account':{'id':'alice','username':'Alice'}}
            with patch.dict('os.environ', {'CARRYON_REGISTRY_DIR':str(root/'registry')}), patch('carryon.onboarding.request', side_effect=[invitation,result,{"members":[]}]) as request, patch('carryon.services.start') as start:
                state = exchange(directory, {'action':'prepare','url':'https://example.test','autoStart':False,'control':False})
                self.assertEqual(state['state'], 'waiting')
                self.assertNotIn('secret', state)
                self.assertEqual(exchange(directory, {'action':'prepare','url':'https://example.test','autoStart':False})['qrURL'], invitation['url'])
                self.assertEqual(request.call_count, 1)
                state = exchange(directory, {'action':'poll'})
                self.assertEqual(state['state'], 'bound'); self.assertFalse(state['running'])
                self.assertEqual(exchange(directory, {'action':'prepare'})['state'], 'bound')
                start.assert_not_called()
                self.assertEqual(len(json.loads((directory/'cloud.json').read_text())['bindings']), 1)

    def test_expiry_preserves_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'onboarding.json').write_text(json.dumps({'state':'waiting','url':'https://example.test','autoStart':False,'pending':{'expiresAt':0}}))
            with patch.dict('os.environ', {'CARRYON_REGISTRY_DIR':str(root/'registry')}):
                with self.assertRaisesRegex(ValueError, '过期'): exchange(root, {'action':'poll'})
            self.assertEqual(json.loads((root/'onboarding.json').read_text())['state'], 'configured')

    def test_unknown_operations_fail_closed(self):
        with self.assertRaises(PermissionError): capability('POST','/api/threads/id/operations',{'action':'unknown'})
        self.assertEqual(capability('GET','/api/threads/id/artifacts/hash'),'files')


class OnboardingRequestErrorTests(unittest.TestCase):
    def test_native_binding_error_survives_http_transport(self):
        import io
        import urllib.error
        from carryon.onboarding import request
        error = urllib.error.HTTPError('https://example.test/console/binding/manage',403,'Forbidden',{},
            io.BytesIO(json.dumps({'error':'设备凭证无效'}).encode()))
        with patch('carryon.onboarding.urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValueError,'设备凭证无效，请重新绑定'):
                request('https://example.test','manage',{'action':'list'})

    def test_non_json_http_error_keeps_status(self):
        import io
        import urllib.error
        from carryon.onboarding import request
        error = urllib.error.HTTPError('https://example.test',502,'Bad Gateway',{},io.BytesIO(b'<html>bad gateway</html>'))
        with patch('carryon.onboarding.urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValueError,'HTTP 502'):
                request('https://example.test','start',{})
