import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from carryon.workspaces import create, initialize
from carryon.services import records, remove
from carryon.app_server import AppServer, project


class WorkspaceIsolationTests(unittest.TestCase):
    @patch("carryon.usage.executable", return_value="codex")
    def test_one_ipc_and_independent_new_workspaces(self, _executable):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with patch.dict(os.environ, {'CARRYON_REGISTRY_DIR':str(root/'registry'), 'CODEX_HOME':str(root/'actual-codex')}):
                first = initialize(root/'default')
                self.assertEqual(first['codexHome'], str(root/'actual-codex'))
                self.assertEqual(initialize(root/'default'), first)
                with self.assertRaisesRegex(ValueError,'已有'): initialize(root/'another-ipc')
                a, b = create('A'), create('B')
                self.assertNotEqual(a['codexHome'], b['codexHome'])
                self.assertNotEqual(a['codexHome'], first['codexHome'])
                self.assertFalse((Path(a['codexHome'])/'auth.json').exists())
                marker = Path(a['codexHome'])/'session'; marker.write_text('keep')
                remove(a['directory'])
                with self.assertRaisesRegex(ValueError, '已删除'):
                    initialize(a['directory'])
                self.assertTrue(records()[a['directory']]['removed'])
                self.assertEqual(marker.read_text(),'keep')
                self.assertFalse(records()[b['directory']]['removed'])

    def test_projection_preserves_native_turn_and_approval(self):
        request = {'id':3, 'method':'item/commandExecution/requestApproval','params':{'threadId':'a'}}
        state = project({'id':'a','cwd':'/tmp','status':{'type':'active'},'turns':[{'id':'turn','status':'inProgress',
            'items':[{'id':'user','type':'userMessage','content':[{'type':'text','text':'hello'}]},
                     {'id':'agent','type':'agentMessage','text':'response'}]}]}, [request])
        self.assertEqual(state['turns'][0]['params']['input'][0]['text'],'hello')
        self.assertEqual(state['requests'][0],request)
        self.assertEqual(state['threadRuntimeStatus']['type'],'active')

    def test_real_app_server_isolation_without_model_execution(self):
        from carryon.usage import executable
        from carryon.errors import BridgeError
        try:
            executable()
        except BridgeError:
            self.skipTest('Native integration requires an installed Codex executable')
        with tempfile.TemporaryDirectory() as temp:
            a, b = AppServer(Path(temp)/'a'), AppServer(Path(temp)/'b')
            a.home.mkdir(); b.home.mkdir()
            try:
                a.connect(); b.connect()
                self.assertIsNone(a.rpc('account/read', {'refreshToken':False})['account'])
                thread = a.rpc('thread/start', {'cwd':str(a.home),'approvalPolicy':'on-request','sandbox':'workspace-write'})['thread']
                self.assertTrue(Path(thread['path']).is_relative_to(a.home))
                self.assertEqual(a.rpc('thread/read',{'threadId':thread['id'],'includeTurns':False})['thread']['id'],thread['id'])
                self.assertNotIn(thread['id'],[t['id'] for t in b.rpc('thread/list',{'limit':100})['data']])
                from carryon.ipc import IPCError
                with self.assertRaises(IPCError): b.rpc('thread/read',{'threadId':thread['id'],'includeTurns':False})
            finally: a.close(); b.close()

class AppServerDeliveryTests(unittest.TestCase):
    def test_direct_creation_tracks_native_terminal_status_and_retries_do_not_create(self):
        from carryon.app_server_bridge import AppServerBridge
        from carryon.store import Journal
        from unittest.mock import Mock
        for terminal in ('failed','interrupted','completed'):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as temp:
                journal=Journal(Path(temp)/'jobs.sqlite'); bridge=AppServerBridge(Path(temp),journal); bridge.workspace_directory=Path(temp)
                ipc=Mock();ipc.authenticated=True;ipc.connected=True;ipc.lock=__import__('threading').RLock();ipc.threads={}
                tid='11111111-1111-1111-1111-111111111111'
                ipc.rpc.return_value={'thread':{'id':tid}}
                ipc.start.return_value={'id':'turn','status':'inProgress'}
                bridge.enabled=True;bridge.ipc=ipc;bridge.workspace=Mock()
                job={'id':'create-test','kind':'create','threadId':'','state':'preparing','created':1,'fingerprint':'hash','clientMessageId':'msg'}
                journal.insert(job)
                from carryon.app_creation import dispatch
                dispatch(bridge,ipc,0,job,'hello',None)
                self.assertEqual(journal.get(job['id'])['state'],'accepted')
                with patch.object(bridge,'turn_evidence',return_value={'status':terminal}):
                    self.assertEqual(bridge._refresh_job(job['id'])['state'],terminal)
                self.assertEqual(ipc.rpc.call_count,1)
                self.assertEqual(journal.get(job['id'])['createdThreadId'],tid)
                journal.conn.close()
