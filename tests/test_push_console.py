from unittest.mock import Mock
import test_console

class PushConsoleTests(test_console.ConsoleTests):
    def test_push_routes_require_session_origin_and_logout_revokes(self):
        push=Mock();push.register.return_value={'registered':True};self.server.push=push
        self.assertEqual(self.call('POST','/console/push',{})[0],401)
        self.login()
        self.assertTrue(self.call('GET','/console/push')[1]['enabled'])
        self.assertEqual(self.call('POST','/console/push',{},origin='https://evil.test')[0],403)
        self.assertEqual(self.call('POST','/console/push',{'installationId':'i'})[0],200)
        session=push.register.call_args.args[1]
        self.assertEqual(self.call('POST','/console/logout',{})[0],200)
        push.unregister_session.assert_called_once_with(session)
        self.assertEqual(self.call('DELETE','/console/push',{'installationId':'i'})[0],401)

    def test_logout_without_body_remains_supported(self):
        self.login()
        self.assertEqual(self.call('POST','/console/logout')[0],200)

    def test_logout_revokes_installation_from_previous_login(self):
        push=Mock();self.server.push=push;self.login()
        self.assertEqual(self.call('POST','/console/logout',{'installationId':'installation','revision':5})[0],200)
        session=push.unregister_session.call_args.args[0]
        push.unregister.assert_called_once_with('installation',session,5)

    def test_transient_registration_failures_are_retryable(self):
        push=Mock();self.server.push=push;self.login()
        for error in (TimeoutError(), ConnectionError(), EOFError()):
            with self.subTest(error=type(error).__name__):
                push.register.side_effect=error
                self.assertEqual(self.call('POST','/console/push',{})[0],503)
        push.register.side_effect=ValueError('invalid token')
        self.assertEqual(self.call('POST','/console/push',{})[0],400)

    def test_background_push_uses_device_websocket_without_phone_subscription(self):
        import time
        from carryon.workspace import Workspace
        from carryon.push import PushService
        from test_workspace import Native
        from test_push import Sender, INSTALL
        from test_cloud import T
        self.bridge.ipc_factory=Native
        self.connector.binding_id='push-test'
        workspace=Workspace(self.bridge);self.bridge.workspace=workspace;workspace.catalog_refresh()
        self.login()
        self.connector.configure(self.device_config());self.bridge.enable()
        deadline=time.monotonic()+4
        while not self.connector.status()['connected'] and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(self.connector.status()['connected'])
        state={'id':T,'threadRuntimeStatus':{'type':'active'},'turns':[{'turnId':'turn-1','status':'inProgress','items':[]}],'requests':[]}
        self.bridge.ipc.states[T]=state;workspace.observe(state)
        sender=Sender();push=PushService(self.server,self.root/'push.sqlite',sender);self.server.push=push
        push.stop.set();push.worker.join();push.stop.clear()
        status,_,_=self.call('POST','/console/push',{'installationId':INSTALL,'token':'ab'*32,'environment':'sandbox','deviceId':'my-mac','revision':1})
        self.assertEqual(status,200)
        state['threadRuntimeStatus']={'type':'idle'};state['turns'][0]['status']='completed';workspace.observe(state)
        push.tick()
        self.assertEqual(sender.sent[-1][2]['aps']['alert']['title'],'任务已完成')
        self.assertEqual(sender.sent[-1][2]['threadId'],T)
        self.assertEqual(self.server.console_streams,{})
        self.call('POST','/console/logout',{})
        self.assertEqual(push.db.execute('SELECT COUNT(*) FROM installations').fetchone()[0],0)
