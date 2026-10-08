import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.file_references import inventory, selections, project, contained, guard
from carryon.sessions.user_messages import unwrap_user_message, SEPARATOR
from carryon.workspaces.workspace_access import required_capabilities


class FileReferenceTests(unittest.TestCase):
    def test_projection_is_text_context_and_preserves_request_and_legal_filename(self):
        path = '/project/' + SEPARATOR + '.txt'
        files = selections([{'name': Path(path).name, 'path': path, 'query': 'txt'}])
        prompt = '请检查\n## My request:\n保留正文。'
        self.assertEqual(unwrap_user_message(project(prompt, files)), (prompt, [path]))
        self.assertEqual(project(prompt, []), prompt)

    def test_untrusted_selection_and_search_fields_are_rejected(self):
        valid = {'name': 'source.py', 'path': '/project/source.py', 'query': 'source'}
        for invalid in [{**valid, 'name': 'other.py'}, {**valid, 'path': 'source.py'},
                        {**valid, 'path': '/project/source.py\n# injected'},
                        {**valid, 'query': '\nsource'}, {**valid, 'root': '/foreign'}]:
            with self.assertRaises(ValueError): selections([invalid])
        with self.assertRaises(ValueError): selections([valid, valid])
        self.assertEqual(required_capabilities('GET', '/api/threads/t/files/search?query=source'), ('files',))

    def test_native_scope_and_path_identity_are_checked_and_unavailable_hits_filtered(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp); (root / 'source.py').write_text('local')
            foreign = Path(outside) / 'private.py'; foreign.write_text('foreign')
            (root / 'escaped.py').symlink_to(foreign)
            hits = [{'root': temp, 'path': name, 'file_name': name, 'match_type': 'file'} for name in ['source.py', 'missing.py', 'escaped.py']]
            calls = []
            runtime = SimpleNamespace(rpc=lambda method, params: calls.append((method, params)) or {'files': hits})
            rows = inventory(runtime, temp, 'source', lambda: None)
            self.assertEqual(rows, [{'name': 'source.py', 'path': str(root / 'source.py'), 'relativePath': 'source.py', 'query': 'source'}])
            self.assertEqual(calls, [('fuzzyFileSearch', {'query': 'source', 'roots': [temp]})])
            for hit in [{**hits[0], 'root': outside}, {**hits[0], 'path': '../source.py'}, {**hits[0], 'file_name': 'other.py'}]:
                hits[:] = [hit]
                with self.assertRaises(IPCError): inventory(runtime, temp, 'source', lambda: None)
            with self.assertRaises(IPCError): contained(temp, str(foreign))

    def test_final_write_rechecks_cwd_and_deleted_or_escaped_file(self):
        import threading
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp); source = root / 'source.py'; source.write_text('local')
            state = {'cwd': temp}; writes = []
            runtime = SimpleNamespace(connected=True, process=object(), session_id='original', lock=threading.RLock(),
                current=lambda _: state, rpc=lambda method, params: {'files': [{'root': params['roots'][0], 'path': 'source.py', 'file_name': 'source.py', 'match_type': 'file'}]})
            files = [{'name': 'source.py', 'path': str(source.resolve()), 'query': 'source'}]
            for change in ['cwd', 'session', 'deleted', 'symlink']:
                callback = guard(runtime, 't', files, None)
                if change == 'cwd': state['cwd'] = outside
                elif change == 'session': runtime.session_id = 'changed'
                elif change == 'deleted': source.unlink()
                else:
                    foreign = Path(outside) / 'source.py'; foreign.write_text('foreign')
                    source.unlink(); source.symlink_to(foreign)
                with self.assertRaises(IPCError): callback(lambda: writes.append('sent'))
                state['cwd'] = temp; runtime.session_id = 'original'
                if source.is_symlink() or not source.exists():
                    source.unlink(missing_ok=True); source.write_text('local')
            guard(runtime, 't', files, None)(lambda: writes.append('sent'))
            self.assertEqual(writes, ['sent'])
