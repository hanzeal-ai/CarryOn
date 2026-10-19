import ast
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from carryon.codex_cli.client import CliClient, endpoint
from carryon.codex_cli.bridge import CliBridge
from carryon.errors import IPCError, BridgeError
from carryon.store import Journal
from carryon.services import records, register, workspace_codex_home, workspace_backend
from carryon.workspaces.workspaces import create

T = '11111111-1111-4111-8111-111111111111'


class CliTests(unittest.TestCase):
    def test_workspace_binding_preserves_external_home_and_does_not_initialize_it(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'CARRYON_REGISTRY_DIR': temp}):
            home = Path(temp).resolve() / 'external'; home.mkdir()
            sentinel = home / 'config.toml'; sentinel.write_text('model="keep-me"\n')
            row = create('CLI', backend='codex-cli', codex_home=home)
            self.assertEqual(sentinel.read_text(), 'model="keep-me"\n')
            self.assertEqual(list(home.iterdir()), [sentinel])
            self.assertEqual(workspace_codex_home(row['directory'], home), home)
            self.assertEqual(workspace_backend(row['directory']), 'codex-cli')
            self.assertEqual(row['cliSocket'], str(home / 'app-server-control/app-server-control.sock'))
            with self.assertRaisesRegex(ValueError, 'socket 已被'):
                create('duplicate', backend='codex-cli', codex_home=home)
            with self.assertRaises(ValueError): register(row['directory'], backend='app-server')
            with self.assertRaises(ValueError): register(row['directory'], cli_socket=Path(temp) / 'changed.sock')

    def test_cli_home_must_not_share_owned_runtime_home(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'CARRYON_REGISTRY_DIR': temp}):
            home = Path(temp) / 'owned'
            register(Path(temp) / 'a', backend='app-server', codex_home=home)
            with self.assertRaisesRegex(ValueError, 'app-server'):
                create('bad', backend='codex-cli', codex_home=home)

    def test_rejects_non_socket_without_starting_any_process(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'regular'; path.touch()
            client = CliClient(temp, socket_path=path)
            with patch('subprocess.Popen', side_effect=AssertionError('must not spawn')):
                with self.assertRaises(IPCError): client.connect()
                client.close()
            self.assertTrue(path.exists())
            with self.assertRaises(ValueError): endpoint(temp, 'relative.sock')

    def test_disconnect_marks_inflight_uncertain_and_remembers_subscriptions(self):
        client = CliClient('/tmp')
        sent = threading.Event(); outcome = []
        client._write = lambda _: sent.set()
        client.following[T] = 'app-server'
        def request():
            try: client.rpc('turn/start', {}, timeout_ms=1000)
            except IPCError as exc: outcome.append(exc)
        thread = threading.Thread(target=request); thread.start(); self.assertTrue(sent.wait(1))
        client.close(); thread.join(2)
        self.assertEqual(client.restore_threads, {T})
        self.assertTrue(outcome[0].uncertain)
        self.assertEqual(client.pending, {})

    def test_reconnect_keeps_targets_across_failed_connect_without_resending(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge = CliBridge(temp, Journal(Path(temp) / 'jobs.sqlite'))
            self.addCleanup(bridge.journal.conn.close)
            old = CliClient(temp); old.restore_threads.add(T); bridge.ipc = old; bridge.enabled = True
            with patch.object(bridge, 'enable', side_effect=BridgeError('unavailable')):
                with self.assertRaises(BridgeError): bridge.reconnect()
            self.assertEqual(bridge.restore_targets, {T})
            replacement = CliClient(temp); seen = []
            replacement.sidebar_snapshot = lambda tid: seen.append(tid)
            def enable(): bridge.ipc = replacement; bridge.enabled = True
            with patch.object(bridge, 'enable', side_effect=enable): bridge.reconnect()
            self.assertEqual(seen, [T])
            bridge.restore_targets.add(T); bridge.disable()
            self.assertFalse(bridge.restore_targets)

    def test_connected_transport_retries_failed_subscription(self):
        from types import SimpleNamespace
        from carryon.lifecycle import BridgeLifecycle
        with tempfile.TemporaryDirectory() as temp:
            bridge = CliBridge(temp, Journal(Path(temp) / 'jobs.sqlite'))
            self.addCleanup(bridge.journal.conn.close)
            calls = []
            def snapshot(tid):
                calls.append(tid)
                if len(calls) == 1: raise IPCError('temporary failure')
            bridge.ipc = SimpleNamespace(connected=True, account_ready=True, sidebar_snapshot=snapshot)
            bridge.enabled = True; bridge.restore_targets = {T}
            lifecycle = BridgeLifecycle(bridge)
            lifecycle.connect()
            self.assertEqual(bridge.restore_targets, {T})
            lifecycle.connect()
            self.assertEqual(calls, [T, T])
            self.assertFalse(bridge.restore_targets)

    def test_auxiliary_cli_connections_preserve_external_transport(self):
        client = CliClient('/tmp', socket_path='/tmp/external.sock')
        with patch('subprocess.Popen', side_effect=AssertionError('must not spawn')):
            peer = client.peer(runtime_directory='/tmp/unused')
        self.assertIsInstance(peer, CliClient)
        self.assertEqual(peer.endpoint, client.endpoint)
        self.assertFalse(hasattr(peer, 'process'))

    def test_cli_side_creation_is_rejected_at_server_boundary(self):
        from carryon.sessions.side_creation import submit
        with tempfile.TemporaryDirectory() as temp:
            bridge = CliBridge(temp, Journal(Path(temp) / 'jobs.sqlite'))
            self.addCleanup(bridge.journal.conn.close)
            client = CliClient(temp)
            self.assertNotIn('side-create', client.supported_operations)
            with patch.object(bridge, 'require', return_value=(client, 0)), patch.object(client, 'peer', side_effect=AssertionError('must not attach')):
                with self.assertRaisesRegex(IPCError, '不支持创建临时聊天'):
                    submit(bridge, T, {'requestId': 'cli-side-denied'})
            self.assertFalse(bridge.journal.list())

    def test_discovery_subscribes_loaded_cli_but_does_not_resume_dormant_history(self):
        client = CliClient('/tmp'); client.connection = object()
        thread = {'id': T, 'cwd': '/tmp', 'status': {'type': 'idle'}, 'turns': []}
        client._event({'method': 'thread/started', 'params': {'thread': thread}})
        self.assertTrue(client.current(T)['_metadataOnly'])
        self.assertNotIn(T, client.following)
        calls = []
        def rpc(method, params):
            calls.append(method)
            if method == 'thread/turns/list': return {'data': [], 'nextCursor': None}
            if method == 'thread/goal/get': return {'goal': None}
            return {'thread': thread}
        client.rpc = rpc
        _, state = client.sidebar_snapshot(T)
        self.assertIn('thread/resume', calls)
        self.assertEqual(state['executionBackend'], 'codex-cli')
        self.assertFalse(state.get('_metadataOnly'))
        client.snapshots.clear(); client.following.clear(); calls.clear()
        thread['status'] = {'type': 'notLoaded'}
        _, state = client.sidebar_snapshot(T)
        self.assertEqual(calls, ['thread/read'])
        self.assertTrue(state['_metadataOnly'])
        self.assertEqual(state['executionBackend'], 'codex-cli')

    def test_adapters_share_contract_without_importing_other_adapters(self):
        root = Path(__file__).resolve().parents[1] / 'carryon'
        for package, forbidden in [('codex_cli', ('carryon.app_server', 'carryon.desktop_ipc')),
                                   ('codex_protocol', ('carryon.app_server', 'carryon.desktop_ipc')),
                                   ('app_server', ('carryon.codex_cli', 'carryon.desktop_ipc'))]:
            for path in (root / package).glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.ImportFrom):
                        self.assertFalse((node.module or '').startswith(forbidden), str(path))
