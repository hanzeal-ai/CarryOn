import tempfile
import time
import unittest
from pathlib import Path
from carryon.bridge import Bridge, BridgeError
from carryon.store import Journal

PARENT='11111111-1111-4111-8111-111111111111'
CHILD='22222222-2222-4222-8222-222222222222'
OTHER='33333333-3333-4333-8333-333333333333'


class Catalog:
    def get(self, tid):
        if tid==CHILD:raise ValueError('ephemeral not persisted')
        return {'id':tid}
    def side_candidates(self):return [CHILD]


class IPC:
    def __init__(self,_):
        self.connected=False
        self.state={'id':CHILD,'ephemeral':True,'sideConversation':True,'forkedFromId':PARENT,
                    'title':'Side title','threadRuntimeStatus':{'type':'active'},'turns':[
                    {'turnId':'t','status':'inProgress','params':{},'items':[{'type':'agentMessage','text':'Live side text'}]}]}
    def connect(self):self.connected=True
    def close(self):self.connected=False
    def current(self,tid):return self.state if tid==CHILD else None


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
