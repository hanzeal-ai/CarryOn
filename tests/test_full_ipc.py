import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path

from connectnow.catalog import Catalog
from connectnow.contracts import SCHEMAS, settings, validate
from connectnow.events import VERSIONS
from connectnow.ipc import DesktopIPC
from connectnow.operations import build, controls, digest
from connectnow.queue import message, projection, transform
from test_operations import state, T


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.items = [message('first', state()), message('second', state())]
        self.items[0]['context']['fileAttachments'] = [{'path': '/tmp/test.txt'}]
    def apply(self, action, **data):
        return transform(action, {'queueFingerprint': digest(self.items), **data}, state('active'), self.items)
    def test_add_preserves_existing_attachments_and_order(self):
        result = self.apply('queue-add', prompt='third')
        self.assertEqual(result[:2], self.items)
        self.assertEqual(result[-1]['context']['prompt'], 'third')
        self.assertEqual(len(self.items), 2)
    def test_edit_changes_text_preserves_context(self):
        result = self.apply('queue-edit', messageId=self.items[0]['id'], prompt='new')
        self.assertEqual(result[0]['text'], 'new')
        self.assertEqual(result[0]['context']['fileAttachments'], self.items[0]['context']['fileAttachments'])
    def test_reorder_exact_membership_and_delete(self):
        ids = [m['id'] for m in reversed(self.items)]
        self.assertEqual(self.apply('queue-reorder', messageIds=ids), list(reversed(self.items)))
        for invalid in (ids[:1], [ids[0]] * 2, ['other', ids[0]]):
            with self.assertRaises(ValueError): self.apply('queue-reorder', messageIds=invalid)
        self.assertEqual(self.apply('queue-delete', messageId=self.items[0]['id']), self.items[1:])
    def test_pause_resume_preserves_content(self):
        self.items[0]['pausedReason'] = 'interrupted'
        result = self.apply('queue-resume', messageId=self.items[0]['id'])
        self.assertNotIn('pausedReason', result[0])
        self.assertEqual(result[0]['text'], 'first')
    def test_stale_queue_rejected_including_clear(self):
        for action in ('queue-add', 'queue-edit', 'queue-delete', 'queue-reorder', 'clear-queue'):
            with self.assertRaises(ValueError): transform(action, {'queueFingerprint': 'stale', 'confirmed': True}, state(), self.items)
    def test_untrusted_app_input_is_never_silently_removed(self):
        self.items[0]['context']['untrustedAppMessage'] = {'text': 'needs confirmation'}
        with self.assertRaises(ValueError): self.apply('queue-add', prompt='new')
        self.assertIn('untrustedAppMessage', self.items[0]['context'])
    def test_read_only_bootstrap(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / '.codex-global-state.json'
            p.write_text(json.dumps({'queued-follow-ups': {T: self.items}}))
            before = p.read_bytes()
            self.assertEqual(Catalog(d).queued(T), self.items)
            self.assertEqual(p.read_bytes(), before)
    def test_duplicate_native_ids_rejected(self):
        with self.assertRaises(ValueError): projection([self.items[0], self.items[0]], 'native')


class ExtendedContractTests(unittest.TestCase):
    def test_all_settings_fields_are_forwarded(self):
        values = {'model': 'native-model', 'effort': 'new-native-effort', 'serviceTier': 'custom-tier',
                  'cwd': '/tmp', 'approvalPolicy': {'granular': {'mcp_elicitations': True, 'rules': True, 'sandbox_approval': True}},
                  'approvalsReviewer': 'user', 'permissions': 'profile-id',
                  'activePermissionProfile': {'id': 'profile-id', 'extends': None},
                  'collaborationMode': {'mode': 'plan', 'settings': {'model': 'native-model', 'reasoning_effort': 'high', 'developer_instructions': None}},
                  'summary': 'concise', 'personality': 'friendly', 'multiAgentMode': 'explicitRequestOnly'}
        self.assertEqual(settings(values, T), values)
        self.assertEqual(build('settings', {'settings': values}, state('active'))[2]['threadSettings'], values)
        self.assertEqual(settings({'sandboxPolicy': {'type': 'workspaceWrite', 'writableRoots': ['/tmp'], 'networkAccess': False}}, T)['sandboxPolicy']['type'], 'workspaceWrite')
    def test_permission_policy_conflicts_and_invalid_enums_rejected(self):
        for patch in ({'permissions': 'p', 'sandboxPolicy': {'type': 'readOnly'}},
                      {'approvalsReviewer': 'unknown'}, {'cwd': 'relative'},
                      {'approvalPolicy': {'granular': {'rules': True}}},
                      {'activePermissionProfile': {'id': 'a'}, 'permissions': 'b'}):
            with self.assertRaises(ValueError): settings(patch, T)
    def request(self, action, method, params):
        s = state('active'); r = {'id': 1, 'method': method, 'params': params};s['requests']=[r]
        return s, {'nativeRequestId':1,'requestFingerprint':digest(r)}
    def test_session_and_persistent_decisions_preserve_native_payload(self):
        params={'proposedExecpolicyAmendment':['git','status'],
                'proposedNetworkPolicyAmendments':[{'host':'example.test','action':'allow'}]}
        s,d=self.request('command-approval','item/commandExecution/requestApproval',params)
        choices=controls(s)['requests'][0]['decisions']
        for decision in choices:
            self.assertEqual(build('command-approval',{**d,'decision':decision},s)[2]['decision'],decision)
        with self.assertRaises(ValueError):build('command-approval',{**d,'decision':{'acceptWithExecpolicyAmendment':{'execpolicy_amendment':['sh']}}},s)
    def test_advertised_decisions_are_authoritative(self):
        s,d=self.request('file-approval','item/fileChange/requestApproval',{'availableDecisions':['cancel']})
        with self.assertRaises(ValueError):build('file-approval',{**d,'decision':'acceptForSession'},s)
        self.assertEqual(build('file-approval',{**d,'decision':'cancel'},s)[2]['decision'],'cancel')
    def test_permission_session_subset_and_strict_review(self):
        s,d=self.request('permissions-approval','item/permissions/requestApproval',{'permissions':{'fileSystem':{'read':['/a','/b']},'network':{'enabled':True}}})
        response={'permissions':{'fileSystem':{'read':['/a']}},'scope':'session','strictAutoReview':True}
        self.assertEqual(build('permissions-approval',{**d,'response':response},s)[2]['response'],response)
        response['permissions']['fileSystem']['read']=['/elsewhere']
        with self.assertRaises(ValueError):build('permissions-approval',{**d,'response':response},s)


class EventTests(unittest.TestCase):
    def setUp(self):
        self.ipc=DesktopIPC('/not-connected');self.ipc.following[T]='owner';self.sent=[];self.changed=[]
        self.ipc._write=self.sent.append;self.ipc.on_change=lambda:self.changed.append(True)
    def event(self, method, source='owner', version=None, **params):
        self.ipc.events.handle({'method':method,'version':VERSIONS[method] if version is None else version,
            'sourceClientId':source,'params':{'conversationId':T,'hostId':'local',**params}})
    def test_following_status_reply_targets_owner(self):
        self.event('thread-stream-following-status-requested',source='wrong')
        self.assertEqual(self.sent,[])
        self.event('thread-stream-following-status-requested')
        self.assertEqual(self.sent[0]['targetClientIds'],['owner'])
        self.assertTrue(self.sent[0]['params']['following'])
    def test_queue_broadcast_owner_and_schema(self):
        m=[message('hello',state())]
        self.event('thread-queued-followups-changed',source='wrong',messages=m)
        self.assertEqual(self.ipc.events.queues,{})
        self.ipc.events.handle({'method':'thread-queued-followups-changed','version':1,'sourceClientId':'owner','params':{'conversationId':T,'messages':m}})
        self.assertEqual(self.ipc.events.queues[T],m)
        self.event('thread-queued-followups-changed',messages='invalid')
        self.assertNotIn(T,self.ipc.events.queues)
    def test_read_archive_unarchive_and_versions(self):
        self.event('thread-read-state-changed',hasUnreadTurn=True)
        self.assertTrue(self.ipc.events.flags[T]['hasUnreadTurn'])
        self.event('thread-archived',version=1)
        self.assertEqual(self.ipc.events.catalog_revision,0)
        self.event('thread-archived');self.assertTrue(self.ipc.events.flags[T]['archived'])
        self.event('thread-unarchived');self.assertFalse(self.ipc.events.flags[T]['archived'])
        self.assertEqual(self.ipc.events.catalog_revision,2)
    def test_reset_invalidates_history_queue_and_pending_requests(self):
        self.ipc.snapshots[T]=(1,state());self.ipc.events.queues[T]=[]
        waiter={'event':threading.Event()};self.ipc.pending['request']=waiter
        self.event('ipc-connection-reset')
        self.assertEqual(self.ipc.snapshots,{})
        self.assertEqual(self.ipc.events.queues,{})
        self.assertTrue(waiter['event'].is_set());self.assertIn('error',waiter)
        self.assertEqual(self.ipc.events.reset_revision,1)


if __name__ == '__main__': unittest.main()
