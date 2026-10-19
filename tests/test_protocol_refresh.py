"""Deterministic read/event interleavings on the shared native projection."""
import threading
import unittest

from carryon.codex_cli.client import CliClient
from carryon.sessions.history_cache import NativeSnapshot


class ProtocolRefreshTests(unittest.TestCase):
    def test_older_read_cannot_replace_newer_notification_or_hydration(self):
        for hydration in (False, True):
            with self.subTest(hydration=hydration):
                client = CliClient('/tmp')
                thread = {'id': 't', 'cwd': '/tmp', 'status': {'type': 'active'}}
                client._event({'method': 'thread/started', 'params': {'thread': thread}})
                entered, release = threading.Event(), threading.Event()
                results = []
                def rpc(*_):
                    entered.set()
                    if not release.wait(2): raise AssertionError('read was not released')
                    return {'thread': thread}
                client.rpc = rpc
                worker = threading.Thread(target=lambda: results.append(client.refresh_snapshot('t')))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    if hydration:
                        with client.lock:
                            client.snapshots['t'] = NativeSnapshot({**client.current('t'),
                                '_metadataOnly': False, 'threadRuntimeStatus': {'type': 'idle'},
                                'turns': [{'turnId': 'completed', 'status': 'completed', 'items': []}]})
                    else:
                        client._event({'method': 'thread/status/changed', 'params': {'threadId': 't', 'status': {'type': 'idle'}}})
                    newest = client.current('t')
                finally:
                    release.set(); worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(results), 1)
                self.assertIs(results[0][1], newest)
                self.assertIs(client.current('t'), newest)
                self.assertEqual(newest['threadRuntimeStatus'], {'type': 'idle'})

    def test_uncontended_read_refreshes_runtime(self):
        client = CliClient('/tmp')
        thread = {'id': 't', 'cwd': '/tmp', 'status': {'type': 'active'}}
        client._event({'method': 'thread/started', 'params': {'thread': thread}})
        client.rpc = lambda *_: {'thread': {**thread, 'status': {'type': 'idle'}}}
        self.assertEqual(client.refresh_snapshot('t')[1]['threadRuntimeStatus'], {'type': 'idle'})
