"""History remains readable independently of the desktop's loaded conversations."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from carryon.bridge import Bridge
from carryon.catalog import Catalog
from carryon.history_cache import NativeSnapshot
from carryon.realtime import Realtime, Subscription
from carryon.store import Journal
from test_subagents import Native, P


class UnloadedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.path = self.home / 'history.jsonl'
        self.path.write_text('')
        with sqlite3.connect(self.home / 'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id,title,name,cwd,archived,source,thread_source,history_mode,rollout_path)')
            db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?)',
                       (P, 'Old conversation', '', str(self.home), 0, 'vscode', 'user', 'paginated', str(self.path)))
        self.journal = Journal(self.home / 'jobs.sqlite')
        self.bridge = Bridge('fixture', Catalog(self.home), self.journal, Native)
        self.bridge.enable()
        self.bridge.realtime = Realtime(self.bridge)
        self.bridge.ipc.snapshot = Mock(side_effect=AssertionError('history must not wait for desktop loading'))
        self.append('task_started', turn_id='turn')
        self.item('user', 'UserMessage', 'hello')
        self.item('answer', 'AgentMessage', 'answer')
        self.append('task_complete', turn_id='turn')

    def tearDown(self):
        self.bridge.disable()
        self.journal.conn.close()
        self.temp.cleanup()

    def append(self, kind, **fields):
        with self.path.open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': kind, **fields}}) + '\n')

    def item(self, identifier, kind, text):
        self.append('item_completed', thread_id=P, turn_id='turn',
                    item={'id': identifier, 'type': kind, 'content': [{'type': 'Text', 'text': text}]})

    def test_unloaded_paginated_history_and_incremental_updates(self):
        first = self.bridge.history(P, limit=1)
        self.assertFalse(first['syncing'])
        self.assertFalse(first['access']['nativeReady'])
        self.assertEqual(first['controls'], {})
        self.assertEqual(first['status']['state'], 'unknown')
        self.assertTrue(first['historyWindow']['hasMore'])
        self.assertEqual(first['historyWindow']['total'], 2)
        full = self.bridge.history(P, limit=40)
        self.assertIn('hello', json.dumps(full['timeline']))
        self.assertIn('answer', json.dumps(full['timeline']))
        self.item('new', 'AgentMessage', 'new persisted result')
        updated = self.bridge.history(P, limit=40)
        self.assertNotEqual(full['historyRevision'], updated['historyRevision'])
        self.assertIn('new persisted result', json.dumps(updated['timeline']))
        self.bridge.ipc.snapshot.assert_not_called()

    def test_confirmed_unloaded_and_unknown_status_have_distinct_revisions(self):
        first = self.bridge.history(P)
        self.bridge.realtime.unavailable[P] = (self.bridge.ipc, time.monotonic(), {'state':'notLoaded','label':'未加载'})
        missing = self.bridge.history(P)
        self.assertEqual(missing['status']['state'], 'notLoaded')
        self.assertNotEqual(first['historyRevision'], missing['historyRevision'])
        self.assertFalse(missing['syncing'])
        self.assertIn('历史已同步', missing['status']['label'])
        self.bridge.realtime.unavailable[P] = (self.bridge.ipc, time.monotonic(), {'state':'unknown','label':'状态未知'})
        self.assertEqual(self.bridge.history(P)['status']['state'], 'unknown')

    def test_native_snapshot_replaces_persisted_status(self):
        persisted = self.bridge.history(P)
        self.bridge.ipc.states[P] = NativeSnapshot({'id':P,'turns':[], 'threadRuntimeStatus':{'type':'active'},'requests':[]})
        native = self.bridge.history(P)
        self.assertEqual(native['source'], 'desktop-snapshot')
        self.assertEqual(native['status']['state'], 'running')
        self.assertNotEqual(native['historyRevision'], persisted['historyRevision'])

    def test_metadata_only_snapshot_does_not_hide_history(self):
        self.bridge.ipc.states[P] = NativeSnapshot({'id':P, '_metadataOnly':True})
        self.assertIn('answer', json.dumps(self.bridge.history(P)['timeline']))

    def test_missing_and_corrupt_history_report_errors_in_stream(self):
        owner = SimpleNamespace(bridge=self.bridge, sync_watches=lambda:None, unavailable={})
        subscription = Subscription(owner)
        subscription.selection.update(threadId=P, historyLimit=40)
        self.path.unlink()
        packet, *_ = subscription.update()
        self.assertIn('error', packet)
        self.assertNotIn('history', packet)
        self.path.write_text('invalid json\n')
        packet, *_ = subscription.update()
        self.assertIn('损坏', packet['error'])
        self.assertNotIn('history', packet)

    def test_legacy_history_pages_beyond_old_two_hundred_message_cap(self):
        with sqlite3.connect(self.home / 'state_5.sqlite') as db:
            db.execute("UPDATE threads SET history_mode='legacy'")
        with self.path.open('w') as stream:
            for index in range(240):
                stream.write(json.dumps({'type':'response_item','payload':{'type':'message',
                    'role':'user' if index % 2 == 0 else 'assistant',
                    'content':[{'type':'input_text' if index % 2 == 0 else 'output_text','text':f'message-{index}'}]}}) + '\n')
        page = self.bridge.history(P, limit=2)
        self.assertEqual(page['historyWindow'], {'limit':2,'total':240,'hasMore':True,'unit':'items'})
        self.assertIn('message-238', json.dumps(page['timeline']))
        self.assertNotIn('message-237', json.dumps(page['timeline']))
        full = self.bridge.history(P, limit=300)
        self.assertFalse(full['historyWindow']['hasMore'])
        self.assertIn('message-0', json.dumps(full['timeline']))
        self.assertEqual(len([i for i in full['timeline'] if i['type'] in ('userMessage','agentMessage')]), 240)

    def test_websocket_reads_local_history_then_switches_to_live(self):
        from test_realtime import WSTests
        transport = WSTests('test_authenticated_event_push_switch_and_revocation')
        transport.setUp()
        transport.server.bridge = self.bridge
        try:
            client, headers = transport.connect()
            self.assertIn(b'101', headers)
            transport.send(client, {'type':'auth','token':transport.server.token})
            transport.send(client, {'type':'subscribe','threadId':P,'subscription':'old','historyLimit':40})
            first = transport.until(client, lambda d:d.get('subscription') == 'old' and 'history' in d)
            self.assertEqual(first['history']['source'], 'local-rollout')
            self.assertFalse(first['history']['syncing'])
            self.assertIn('answer', json.dumps(first['history']['timeline']))
            self.item('appended', 'AgentMessage', 'persisted update')
            updated = transport.until(client, lambda d:'persisted update' in json.dumps(d.get('history',{})))
            self.assertNotEqual(first['history']['historyRevision'], updated['history']['historyRevision'])
            self.bridge.ipc.states[P] = NativeSnapshot({'id':P,'turns':[], 'threadRuntimeStatus':{'type':'idle'},'requests':[]})
            self.bridge.notify()
            live = transport.until(client, lambda d:d.get('history',{}).get('source') == 'desktop-snapshot')
            self.assertEqual(live['history']['status']['state'], 'idle')
        finally:
            transport.tearDown()
