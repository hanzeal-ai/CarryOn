import select
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from carryon.workspaces.catalog_watch import CatalogWatch


class CatalogWatchTests(unittest.TestCase):
    def test_scope_and_explicit_fallback(self):
        for name in ('state_5.sqlite', 'state_5.sqlite-wal', 'state_5.sqlite-journal', '.codex-global-state.json'):
            self.assertTrue(CatalogWatch.relevant(name))
        for name in ('auth.json', 'config.toml', 'state_x.sqlite', 'state_5.sqlite-shm'):
            self.assertFalse(CatalogWatch.relevant(name))
        with tempfile.TemporaryDirectory() as directory:
            watch = CatalogWatch(directory, lambda: None)
            with patch('carryon.workspaces.catalog_watch.select', object()):
                watch.start()
            self.assertEqual(watch.mode, 'fallback-poll')
            watch.close()

    @unittest.skipUnless(hasattr(select, 'kqueue'), 'requires OS kqueue')
    def test_create_write_replace_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            changed = threading.Event()
            watch = CatalogWatch(directory, changed.set)
            watch.start()
            self.addCleanup(watch.close)
            self.assertEqual(watch.mode, 'filesystem-events')
            path = Path(directory) / 'state_5.sqlite-wal'
            def change(action):
                time.sleep(.3)
                changed.clear()
                action()
                self.assertTrue(changed.wait(3), 'missing filesystem invalidation')
            change(lambda: path.write_text('first'))
            change(lambda: path.write_text('second'))
            replacement = Path(directory) / 'replacement'
            replacement.write_text('new inode')
            change(lambda: replacement.replace(path))
            change(lambda: path.write_text('replacement watched'))
            change(path.unlink)

    @unittest.skipUnless(hasattr(select, 'kqueue'), 'requires OS kqueue')
    def test_missing_home_falls_back_and_notifies(self):
        event = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            watch = CatalogWatch(Path(directory) / 'absent', event.set)
            watch.start()
            self.assertEqual(watch.mode, 'fallback-poll')
            self.assertTrue(event.is_set())
            self.assertEqual(watch.files, {})
            watch.close()

    def test_protocol_project_move_delete_invalidate_without_loaded_thread(self):
        from carryon.codex_cli.client import CliClient
        client = CliClient('/tmp')
        for method, params in (
            ('project/changed', {'projectId':'p','changeType':'updated'}),
            ('thread/project/updated', {'threadId':'unloaded','projectId':'p'}),
            ('thread/deleted', {'threadId':'unloaded'}),
        ):
            before = client.events.catalog_revision
            client._event({'method':method,'params':params})
            self.assertEqual(client.events.catalog_revision, before + 1)
        self.assertEqual(client.snapshots, {})

    def test_workspace_refreshes_on_events_reconnect_and_fallback_only(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from carryon.workspaces.workspace import Workspace
        for mode, expected in [('filesystem-events', 3), ('fallback-poll', 4)]:
            workspace = Workspace.__new__(Workspace)
            workspace.catalog_watch = SimpleNamespace(mode=mode)
            workspace.catalog_dirty = threading.Event()
            workspace.catalog_dirty.set()
            workspace.closed = Mock()
            workspace.lock = threading.RLock()
            ipc = SimpleNamespace(events=SimpleNamespace(catalog_revision=0))
            step = [0]
            workspace.closed.is_set.side_effect = lambda: step[0] >= 4
            def require():
                step[0] += 1
                if step[0] == 3: ipc.events.catalog_revision += 1
                return ipc, 2 if step[0] == 4 else 1
            workspace.bridge = SimpleNamespace(status=lambda:{'enabled':True}, require=require,
                events=threading.Condition(), event_revision=0, notify=Mock())
            # Avoid real waiting; the clock jump would trigger the old 15-second sweep.
            workspace.bridge.events.wait = Mock()
            workspace.catalog_refresh = Mock()
            workspace.thread_ids = lambda: set()
            with patch('carryon.workspaces.workspace.time.monotonic', side_effect=range(0, 1000, 20)):
                workspace.run()
            self.assertEqual(workspace.catalog_refresh.call_count, expected)
            waits=workspace.bridge.events.wait.call_args_list
            self.assertTrue(waits)
            if mode == 'filesystem-events':
                self.assertTrue(all(call.args == (None,) for call in waits))
            else:
                self.assertTrue(all(call.args[0] is not None for call in waits))

    def test_notification_cursor_advances_over_hidden_rows(self):
        import json
        import sqlite3
        from carryon.workspaces.workspace import Workspace
        workspace = Workspace.__new__(Workspace)
        workspace.lock = threading.RLock()
        workspace.db = sqlite3.connect(':memory:')
        self.addCleanup(workspace.db.close)
        workspace.db.execute('CREATE TABLE notification_events(sequence INTEGER PRIMARY KEY,body TEXT)')
        workspace.rows = {'visible':{'id':'visible','title':'title','cwd':'/test'}}
        for sequence, tid in [(1,'hidden'),(2,'hidden'),(3,'visible')]:
            workspace.db.execute('INSERT INTO notification_events VALUES(?,?)',(sequence,json.dumps({'threadId':tid})))
        first = workspace.events('reader', 0, 2)
        self.assertEqual(first, {'events':[], 'nextSequence':2, 'hasMore':True})
        second = workspace.events('reader', first['nextSequence'], 2)
        self.assertEqual(len(second['events']), 1)
        self.assertEqual(second['nextSequence'], 3)
        self.assertFalse(second['hasMore'])
        self.assertEqual(workspace.latest_notification_sequence(), 3)

    @unittest.skipUnless(hasattr(select, 'kqueue'), 'requires OS kqueue')
    def test_callback_failure_releases_watch_and_enables_fallback(self):
        def broken_callback():
            raise RuntimeError('notification delivery failed')
        with tempfile.TemporaryDirectory() as directory:
            watch = CatalogWatch(directory, broken_callback)
            watch.start()
            self.addCleanup(watch.close)
            self.assertEqual(watch.mode, 'filesystem-events')
            (Path(directory) / 'state_5.sqlite').write_text('event')
            watch.thread.join(3)
            self.assertFalse(watch.thread.is_alive())
            self.assertEqual(watch.mode, 'fallback-poll')
            self.assertEqual(watch.error, 'RuntimeError')
            self.assertIsNone(watch.queue)
            self.assertEqual(watch.files, {})

    def test_workspace_read_failure_uses_bounded_retry(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from carryon.workspaces.workspace import Workspace
        workspace = Workspace.__new__(Workspace)
        workspace.closed = threading.Event()
        workspace.catalog_dirty = threading.Event()
        workspace.lock = threading.RLock()
        workspace.bridge = SimpleNamespace(status=Mock(side_effect=ValueError('disconnected')),
            events=threading.Condition(), event_revision=0)
        workspace.bridge.events.wait = Mock(side_effect=lambda timeout: workspace.closed.set())
        workspace.run()
        workspace.bridge.events.wait.assert_called_once_with(2)
        self.assertIn('ValueError', workspace.error)
        self.assertTrue(workspace.catalog_dirty.is_set())

    def test_workspace_require_failure_forces_authoritative_recovery(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from carryon.workspaces.workspace import Workspace
        workspace = Workspace.__new__(Workspace)
        workspace.closed = threading.Event()
        workspace.catalog_dirty = threading.Event()
        workspace.catalog_watch = SimpleNamespace(mode='filesystem-events')
        workspace.lock = threading.RLock()
        ipc = SimpleNamespace(events=SimpleNamespace(catalog_revision=0))
        calls = [0]
        def require():
            calls[0] += 1
            if calls[0] == 2:
                raise ValueError('temporary runtime loss')
            return ipc, 1
        def refresh():
            workspace.error = None
            if calls[0] == 3:
                workspace.closed.set()
        workspace.catalog_refresh = Mock(side_effect=refresh)
        workspace.thread_ids = lambda: set()
        workspace.bridge = SimpleNamespace(status=lambda:{'enabled':True}, require=require,
            events=threading.Condition(), event_revision=0, notify=Mock())
        workspace.bridge.events.wait = Mock()
        workspace.run()
        self.assertEqual(workspace.catalog_refresh.call_count, 2)
        self.assertIsNone(workspace.error)
        self.assertFalse(workspace.catalog_dirty.is_set())
