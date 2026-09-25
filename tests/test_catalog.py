import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from carryon.catalog import Catalog


class CatalogTests(unittest.TestCase):
    def test_shared_git_repository_does_not_guess_native_project(self):
        with tempfile.TemporaryDirectory() as home, closing(sqlite3.connect(':memory:')) as db:
            state={'local-projects':{'one':{'rootPaths':['/repo/one']},'two':{'rootPaths':['/repo/two']}}}
            (Path(home)/'.codex-global-state.json').write_text(json.dumps(state))
            db.execute('CREATE TABLE threads(id,project_id)')
            rows=[{'id':'unassigned','cwd':'/worktree/branch'}]
            with patch('carryon.catalog.subprocess.run') as run:
                run.return_value.returncode=0
                run.return_value.stdout='/repo/.git\n'
                Catalog(home).classify_projects(db,rows)
            self.assertNotIn('nativeProjectId',rows[0])

    def test_multiple_roots_preserve_native_identity_and_infer_unique_owner(self):
        with tempfile.TemporaryDirectory() as home, closing(sqlite3.connect(':memory:')) as db:
            state = {'local-projects': {
                'bundle': {'name': '产品矩阵', 'rootPaths': ['/project/web', '/project/api']},
                'shared': {'name': '共享目录项目', 'rootPaths': ['/project/web']},
            }, 'projectless-thread-ids': ['recent']}
            (Path(home) / '.codex-global-state.json').write_text(json.dumps(state))
            db.execute('CREATE TABLE threads(id,project_id)')
            db.executemany('INSERT INTO threads VALUES(?,?)', [('web','bundle'), ('api','bundle'), ('other','shared')])
            rows = [{'id': tid, 'cwd': cwd} for tid,cwd in [
                ('web','/project/web'), ('api','/project/api'), ('other','/project/web'),
                ('inferred','/project/api/src'), ('ambiguous','/project/web/src'), ('recent','/project/api')]]
            Catalog(home).classify_projects(db, rows)
            result = {r['id']: r for r in rows}
            for tid in ('web','api','inferred'):
                self.assertEqual(result[tid]['nativeProjectId'], 'bundle')
                self.assertEqual(result[tid]['projectName'], '产品矩阵')
                self.assertEqual(result[tid]['projectRoots'], ['/project/web','/project/api'])
                self.assertEqual(result[tid]['projectRoot'], '/project/web')
            self.assertEqual(result['other']['nativeProjectId'], 'shared')
            self.assertNotIn('nativeProjectId', result['ambiguous'])
            self.assertTrue(result['recent']['projectless'])
            self.assertNotIn('nativeProjectId', result['recent'])

    def test_display_name_and_internal_thread_filter(self):
        with tempfile.TemporaryDirectory() as home:
            with closing(sqlite3.connect(Path(home) / 'state_5.sqlite')) as db:
                db.execute('CREATE TABLE threads(id,title,name,cwd,updated_at,created_at,history_mode,archived,source,thread_source)')
                db.executemany('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?)', [
                    ('one','raw private prompt','Readable title','/test',3,1,'paginated',0,'vscode','user'),
                    ('two','internal prompt','Internal','/test',4,1,'legacy',0,'vscode','subagent'),
                    ('three','archived','Old','/test',5,1,'legacy',1,'vscode','user'),
                ])
                db.commit()
            catalog = Catalog(home)
            rows = catalog.list()
            self.assertEqual([r['id'] for r in rows], ['one'])
            self.assertEqual(rows[0]['title'], 'Readable title')
            self.assertEqual(len(catalog.list(search='Readable')), 1)
            with catalog.connection() as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM threads').fetchone()[0],3)
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')

    def test_projectless_uses_codex_membership_instead_of_directory_names(self):
        with tempfile.TemporaryDirectory() as home:
            state = {
                'projectless-thread-ids': ['explicit', 'native'],
                'thread-project-assignments': {'assigned': {'projectId': 'saved'}},
                'local-projects': {'saved': {'rootPaths': ['/workspace/project']}},
            }
            (Path(home) / '.codex-global-state.json').write_text(json.dumps(state))
            with closing(sqlite3.connect(Path(home) / 'state_5.sqlite')) as db:
                db.execute('CREATE TABLE threads(id,title,name,cwd,updated_at,created_at,history_mode,archived,source,thread_source,project_id)')
                examples = [
                    ('explicit', '/workspace/project', None, True),
                    ('unassigned', '/temporary/xue', None, True),
                    ('similar-name', '/workspace/project-other', None, True),
                    ('assigned', '/worktrees/branch', None, False),
                    ('root', '/workspace/project', None, False),
                    ('child', '/workspace/project/web', None, False),
                    ('native', '/worktrees/new', 'native-project', False),
                ]
                for tid, cwd, pid, _ in examples:
                    db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                               (tid,tid,tid,cwd,1,1,'legacy',0,'vscode','user',pid))
                db.commit()
            rows = {r['id']: r for r in Catalog(home).list()}
            for tid, cwd, _, expected in examples:
                self.assertEqual(rows[tid]['projectless'], expected, tid)
                self.assertEqual(rows[tid]['cwd'], cwd)

    def test_worktree_and_subdirectory_share_saved_project_root(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); home = base / 'home'; home.mkdir()
            repo = base / 'project'; repo.mkdir(); tree = base / 'branch'
            subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '--allow-empty', '-m', 'fixture'], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-b', 'branch', str(tree)], check=True, capture_output=True)
            (home / '.codex-global-state.json').write_text(json.dumps({'local-projects': {'saved': {'rootPaths': [str(repo)]}}}))
            with closing(sqlite3.connect(home / 'state_5.sqlite')) as db:
                db.execute('CREATE TABLE threads(id,title,name,cwd,updated_at,created_at,history_mode,archived,source,thread_source)')
                for tid, cwd in [('main', repo), ('branch', tree), ('child', repo / 'src')]:
                    db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?)', (tid, tid, tid, str(cwd), 1, 1, 'legacy', 0, 'vscode', 'user'))
                db.commit()
            rows = Catalog(home).list()
            self.assertEqual({row['projectRoot'] for row in rows}, {str(repo)})
            self.assertFalse(any(row['projectless'] for row in rows))
