import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from carryon.api import dispatch
from carryon.bridge import Bridge
from carryon.catalog import Catalog
from carryon.errors import BridgeError
from carryon.history_cache import NativeSnapshot
from carryon.ipc import IPCError
from carryon.operations import METHODS
from carryon.store import Journal
from carryon.timeline import project_item

P = '11111111-1111-4111-8111-111111111111'
C = '22222222-2222-4222-8222-222222222222'
R = '33333333-3333-4333-8333-333333333333'


class Native:
    def __init__(self, _): self.connected = False; self.states = {}; self.calls = []
    def connect(self): self.connected = True
    def close(self): self.connected = False
    def current(self, tid): return self.states.get(tid)
    def snapshot(self, tid):
        if tid not in self.states: raise IPCError('no-client-found')
        return 'owner', self.states[tid]
    sidebar_snapshot = snapshot
    def watch(self, tid): pass
    def unwatch(self, tid): pass
    def request(self, method, params, version, owner, guard):
        guard(lambda: self.calls.append((method, params)))
        return {'result': {'ok': True}}
    def start(self, tid, prompt, owner, message_id, guard, **kw):
        guard(lambda: self.calls.append(('start', tid, prompt)))
        return {'id': 'next-turn'}


class SubagentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        with sqlite3.connect(self.home / 'state_5.sqlite') as conn:
            conn.execute('CREATE TABLE threads(id,title,name,cwd,created_at,updated_at,archived,source,thread_source,history_mode,rollout_path)')
            for tid, parent, name in [(P, None, 'Parent'), (C, P, 'worker'), (R, P, 'review')]:
                source = json.dumps({'subagent': {'thread_spawn': {'parent_thread_id': parent, 'agent_path': '/root/' + name}}}) if parent else 'vscode'
                conn.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?,?)', (tid, '', '', str(self.home), 1, 1, 0, source, 'subagent' if parent else 'user', 'paginated', str(self.home / (tid + '.jsonl'))))
                (self.home / (tid + '.jsonl')).write_text('')
        self.journal = Journal(self.home / 'jobs.sqlite')
        self.bridge = Bridge('fixture', Catalog(self.home), self.journal, Native)
        self.bridge.enable()
        self.bridge.ipc.states[P] = NativeSnapshot({'id': P, 'turns': [{'turnId': 'p', 'items': [
            {'id': 'spawn', 'type': 'collabAgentToolCall', 'tool': 'spawnAgent', 'status': 'completed', 'senderThreadId': P, 'receiverThreadIds': [C]},
            {'id': 'background', 'type': 'subAgentActivity', 'kind': 'started', 'agentThreadId': R, 'agentPath': '/root/review'}]}]})
        self.bridge.ipc.states[C] = NativeSnapshot({'id': C, 'threadRuntimeStatus': {'type': 'idle'}, 'requests': [],
            'turns': [{'turnId': 'child-turn', 'status': 'completed', 'items': [], 'params': {'input': [{'type': 'text', 'text': 'original'}]}}]})

    def tearDown(self):
        self.bridge.disable(); self.journal.conn.close(); self.temp.cleanup()

    def append(self, tid, category, payload):
        with (self.home / (tid + '.jsonl')).open('a') as f:
            f.write(json.dumps({'type': category, 'payload': payload}) + '\n')

    def event(self, item, tid=R, turn='review-turn'):
        self.append(tid, 'event_msg', {'type': 'item_completed', 'thread_id': tid, 'turn_id': turn, 'item': item})

    def wait_job(self, rid):
        for _ in range(100):
            job = self.journal.get(rid)
            if job['state'] not in ('preparing', 'dispatching'): return job
            time.sleep(.01)
        self.fail('dispatch did not complete')

    def test_list_uses_parent_identity_and_shared_access(self):
        code, result = dispatch(self.bridge, 'GET', f'/api/threads/{P}/subagents', remote=True)
        self.assertEqual(code, 200)
        self.assertEqual([(t['id'], t['access']['canInteract']) for t in result['threads']], [(C, True), (R, False)])
        self.assertEqual(result['threads'][1]['title'], 'Review')
        self.assertEqual(self.bridge.subagents.list(C), {'threads': []})
        with self.assertRaises(ValueError): self.bridge.subagents.list('missing')

    def test_readonly_rejects_every_write_even_if_it_has_live_owner(self):
        self.bridge.ipc.states[R] = {**self.bridge.ipc.states[C], 'id': R}
        for action in METHODS:
            with self.subTest(action=action), self.assertRaises(BridgeError) as error:
                dispatch(self.bridge, 'POST', f'/api/threads/{R}/operations', {'requestId': 'readonly-' + action, 'action': action}, remote=True, control=True)
            self.assertEqual(error.exception.status, 403)
        for endpoint in ('compose', 'messages'):
            with self.assertRaises(BridgeError): dispatch(self.bridge, 'POST', f'/api/threads/{R}/{endpoint}', {'requestId': 'readonly-message', 'prompt': 'must not send'})
        with self.assertRaises(BridgeError): dispatch(self.bridge, 'POST', '/api/controller', {'threadId': R})
        self.assertEqual(self.bridge.ipc.calls, [])
        self.assertEqual(self.journal.list(), [])
        self.assertEqual(self.bridge.history(R)['controls'], {})

    def test_interactive_uses_main_message_and_operation_dispatch(self):
        code, job = dispatch(self.bridge, 'POST', f'/api/threads/{C}/operations', {'requestId': 'child-settings', 'action': 'settings', 'settings': {'model': 'native-model'}})
        self.assertEqual(code, 202); self.assertEqual(self.wait_job(job['id'])['state'], 'completed')
        self.assertEqual(self.bridge.ipc.calls[0], ('thread-follower-update-thread-settings', {'conversationId': C, 'threadSettings': {'model': 'native-model'}}))
        _, job = dispatch(self.bridge, 'POST', f'/api/threads/{C}/compose', {'requestId': 'child-message', 'prompt': 'continue'})
        self.assertEqual(self.wait_job(job['id'])['state'], 'accepted')
        self.assertEqual(self.bridge.ipc.calls[-1], ('start', C, 'continue'))
        with self.assertRaises(BridgeError): dispatch(self.bridge, 'POST', f'/api/threads/{C}/messages', {'requestId': 'remote-denied', 'prompt': 'no'}, remote=True, control=False)

    def test_no_owner_is_readable_but_never_becomes_write_authority(self):
        self.bridge.ipc.states.pop(C)
        history = self.bridge.history(C)
        self.assertTrue(history['access']['canInteract'])
        self.assertFalse(history['access']['nativeReady'])
        self.assertEqual(history['controls'], {})
        self.assertEqual(history['runtime']['type'], 'notLoaded')
        _, job = dispatch(self.bridge, 'POST', f'/api/threads/{C}/messages', {'requestId': 'no-owner-message', 'prompt': 'no'})
        self.assertEqual(self.wait_job(job['id'])['state'], 'failed')
        self.assertEqual(self.bridge.ipc.calls, [])

    def test_persisted_history_has_output_artifacts_and_no_internal_context(self):
        self.append(R, 'event_msg', {'type': 'task_started', 'turn_id': 'review-turn', 'started_at': 1})
        self.append(R, 'response_item', {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': 'PRIVATE-INSTRUCTIONS'}]})
        self.event({'type': 'Reasoning', 'id': 'reason', 'summary_text': ['visible summary'], 'raw_content': ['PRIVATE-REASONING'], 'encrypted_content': 'PRIVATE-CIPHER'})
        self.event({'type': 'CommandExecution', 'id': 'cmd', 'command': ['echo', 'hi'], 'aggregated_output': 'hi\n' * 30000, 'status': 'completed', 'exit_code': 0})
        self.event({'type': 'AgentMessage', 'id': 'reply', 'phase': 'final_answer', 'content': [{'type': 'Text', 'text': '[result](/tmp/result.txt)'}]})
        self.append(R, 'response_item', {'type': 'message', 'id': 'reply', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '[result](/tmp/result.txt)'}]})
        self.append(R, 'event_msg', {'type': 'task_complete', 'turn_id': 'review-turn', 'duration_ms': 2500})
        history = self.bridge.history(R)
        encoded = json.dumps(history)
        self.assertNotIn('PRIVATE-', encoded)
        items = {i['nativeId']: i for i in history['timeline'] if 'nativeId' in i}
        self.assertEqual(items['cmd']['data']['aggregatedOutput'], 'hi\n' * 30000)
        self.assertEqual(items['reason']['text'], 'visible summary')
        self.assertEqual(items['reply']['artifacts'][0]['path'], '/tmp/result.txt')
        self.assertEqual(sum(i.get('nativeId') == 'reply' for i in history['timeline']), 1)
        revision = history['historyRevision']
        self.event({'type': 'AgentMessage', 'id': 'next', 'content': [{'type': 'Text', 'text': 'new update'}]})
        self.assertNotEqual(self.bridge.history(R)['historyRevision'], revision)
        self.assertIn('new update', json.dumps(self.bridge.history(R)))

    def test_persisted_parent_spawn_and_unknown_relationship_fail_closed(self):
        self.bridge.ipc.states.pop(P)
        self.assertFalse(self.bridge.subagents.access(self.bridge.catalog.get(C))['canInteract'])
        self.event({'type': 'CollabAgentToolCall', 'id': 'spawn', 'tool': 'spawn_agent', 'sender_thread_id': P, 'receiver_thread_ids': [C]}, tid=P, turn='parent-turn')
        self.assertTrue(self.bridge.subagents.access(self.bridge.catalog.get(C))['canInteract'])
        self.assertFalse(self.bridge.subagents.access(self.bridge.catalog.get(R))['canInteract'])
        self.bridge.ipc.states[P] = {'id': P, 'turns': []}
        self.assertTrue(self.bridge.subagents.access(self.bridge.catalog.get(C))['canInteract'])

    def test_raw_user_inputs_are_not_display_events_but_canonical_quotes_are_preserved(self):
        self.append(R, 'event_msg', {'type': 'task_started', 'turn_id': 'review-turn'})
        for text in ('<recommended_plugins>PRIVATE-PLUGINS</recommended_plugins>',
                     '# AGENTS.md instructions\nPRIVATE-RULES\n<environment_context>PRIVATE-ENV</environment_context>',
                     'PRIVATE-UNMARKED inherited input'):
            self.append(R, 'response_item', {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]})
        quoted = 'Please explain this quoted <environment_context> and # AGENTS.md instructions'
        self.event({'type': 'UserMessage', 'id': 'visible-user', 'content': [{'type': 'Text', 'text': quoted}]})
        self.event({'type': 'AgentMessage', 'id': 'visible-reply', 'content': [{'type': 'Text', 'text': 'Visible answer'}]})
        for limit in (None, 40):
            history = self.bridge.history(R, limit=limit)
            self.assertNotIn('PRIVATE-', json.dumps(history))
            self.assertIn(quoted, json.dumps(history))
            self.assertIn('Visible answer', json.dumps(history))
        self.assertEqual(self.bridge.history(R, limit=40)['historyWindow']['total'], 2)

    def test_http_history_is_bounded_and_validates_limits(self):
        from carryon.images import image_id
        import base64
        artifact = self.home / 'older.txt'
        artifact.write_text('older output')
        for i in range(55):
            text = f'[older]({artifact})' if i == 0 else str(i)
            self.event({'type': 'AgentMessage', 'id': str(i), 'content': [{'type': 'Text', 'text': text}]})
        for remote in (False, True):
            _, history = dispatch(self.bridge, 'GET', f'/api/threads/{R}/history', remote=remote)
            self.assertEqual(history['historyWindow'], {'limit': 40, 'total': 55, 'hasMore': True, 'unit': 'items'})
            self.assertEqual(len([i for i in history['timeline'] if i['type'] == 'agentMessage']), 40)
            _, history = dispatch(self.bridge, 'GET', f'/api/threads/{R}/history?limit=55', remote=remote)
            self.assertFalse(history['historyWindow']['hasMore'])
            for value in ('', '0', '-1', '4001', '1.5', 'all', '1&limit=2'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    dispatch(self.bridge, 'GET', f'/api/threads/{R}/history?limit={value}', remote=remote)
        # Internal complete history remains available to validate older resource links.
        self.assertEqual(len([i for i in self.bridge.history(R)['timeline'] if i['type'] == 'agentMessage']), 55)
        _, output = dispatch(self.bridge, 'GET', f'/api/threads/{R}/artifacts/{image_id(str(artifact))}', remote=True)
        self.assertEqual(base64.b64decode(output['base64']), b'older output')

    def test_descendants_are_complete_without_duplicate_or_unrelated_threads(self):
        with self.bridge.catalog.connection() as conn:
            self.assertEqual([row['id'] for row in self.bridge.catalog.children(P)], [C, R])
        with sqlite3.connect(self.home / 'state_5.sqlite') as conn:
            conn.execute('UPDATE threads SET source=? WHERE id=?', (json.dumps({'subagent': {'thread_spawn': {'parent_thread_id': C}}}), R))
        self.assertEqual([row['id'] for row in self.bridge.catalog.children(P)], [C, R])
        self.assertEqual([row['id'] for row in self.bridge.catalog.children(C)], [R])

    def test_inline_and_directory_use_current_conversation_title(self):
        item = project_item({'type': 'subAgentActivity', 'id': 'event', 'agentThreadId': R,
                             'agentPath': '/root/old_task_name', 'kind': 'completed'}, {'turnId': 't'}, 0)
        history = {'timeline': [item], 'historyRevision': 'original'}
        with sqlite3.connect(self.home / 'state_5.sqlite') as conn:
            conn.execute('UPDATE threads SET title=? WHERE id=?', ('实际子会话标题', R))
        result = self.bridge.subagents.resolve_titles(history)
        self.assertEqual(result['timeline'][0]['subagents'][0]['title'], '实际子会话标题')
        self.assertEqual(self.bridge.subagents.list(P)['threads'][1]['title'], '实际子会话标题')
        self.assertEqual(item['subagents'][0]['title'], 'Old task name')
        with sqlite3.connect(self.home / 'state_5.sqlite') as conn:
            conn.execute('UPDATE threads SET title=? WHERE id=?', ('重命名后', R))
        renamed = self.bridge.subagents.resolve_titles(history)
        self.assertEqual(renamed['timeline'][0]['subagents'][0]['title'], '重命名后')
        self.assertNotEqual(renamed['historyRevision'], result['historyRevision'])

    def test_collaboration_reference_prefers_conversation_title_to_agent_name(self):
        item = project_item({'type': 'collabAgentToolCall', 'receiverThreadIds': [C],
                             'receiverThreads': [{'threadId': C, 'thread': {'title': '会话标题', 'name': 'Agent 昵称'}}]}, {'turnId': 't'}, 0)
        self.assertEqual(item['subagents'][0]['title'], '会话标题')

    def test_inline_event_has_stable_target_without_name_inference(self):
        item = project_item({'type': 'subAgentActivity', 'id': 'event', 'agentThreadId': R, 'agentPath': '/root/sol_release_review', 'kind': 'completed'}, {'turnId': 't'}, 0)
        self.assertEqual(item['subagents'][0]['id'], R)
        self.assertEqual(item['title'], 'Sol release review · 已完成')
        self.assertNotIn('subagents', project_item({'type': 'agentMessage', 'text': 'Review finished'}, {'turnId': 't'}, 0))

    def test_history_pagination_and_corrupt_record_are_explicit(self):
        for i in range(4): self.event({'type': 'AgentMessage', 'id': str(i), 'content': [{'type': 'Text', 'text': str(i)}]}, turn=str(i))
        history = self.bridge.history(R, limit=2)
        self.assertEqual(history['historyWindow'], {'limit': 2, 'total': 4, 'hasMore': True, 'unit': 'items'})
        self.assertEqual(len(self.bridge.history(R, limit=4)['turns']), 4)
        with (self.home / (R + '.jsonl')).open('a') as f: f.write('corrupt\n')
        with self.assertRaisesRegex(ValueError, '损坏'): self.bridge.history(R)

    def test_large_rollout_is_scanned_once_then_only_appended_bytes_and_requested_page(self):
        self.append(R, 'response_item', {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': 'private' * (3 * 1024 * 1024)}]})
        for i in range(60): self.event({'type': 'AgentMessage', 'id': str(i), 'content': [{'type': 'Text', 'text': 'entry ' + str(i)}]})
        history = self.bridge.history(R, limit=5)
        self.assertEqual(len([i for i in history['timeline'] if i['type'] == 'agentMessage']), 5)
        self.assertTrue(history['historyWindow']['hasMore'])
        index = self.bridge.catalog.rollout_index(R)
        scanned = index.scanned_bytes
        self.assertGreater(scanned, 16 * 1024 * 1024)
        self.bridge.history(R, limit=5)
        self.assertEqual(index.scanned_bytes, scanned)
        before = index.path.stat().st_size
        self.event({'type': 'AgentMessage', 'id': 'appended', 'content': [{'type': 'Text', 'text': 'latest'}]})
        latest = self.bridge.history(R, limit=5)
        self.assertEqual(index.scanned_bytes - scanned, index.path.stat().st_size - before)
        self.assertEqual(latest['timeline'][-1]['text'], 'latest')
        self.assertEqual(self.bridge.history(R, limit=100)['historyWindow']['total'], 61)

    def test_incomplete_append_and_replaced_file_do_not_reuse_old_offsets(self):
        path = self.home / (R + '.jsonl')
        path.write_text('{"type":"event_msg","payload":')
        self.assertEqual(self.bridge.history(R)['timeline'], [])
        with path.open('a') as f: f.write('{"type":"item_completed","turn_id":"t","item":{"type":"AgentMessage","id":"a","content":[{"type":"Text","text":"new"}]}}}\n')
        self.assertEqual(self.bridge.history(R)['timeline'][-1]['text'], 'new')
        path.write_text('')
        self.assertEqual(self.bridge.history(R)['timeline'], [])
