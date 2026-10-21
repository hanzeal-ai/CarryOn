import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from carryon.sessions.catalog import Catalog
from native_project_fixture import replace_projects


class CatalogTests(unittest.TestCase):
    def test_shared_git_repository_does_not_guess_native_project(self):
        with tempfile.TemporaryDirectory() as home, closing(sqlite3.connect(':memory:')) as db:
            state={'local-projects':{'one':{'rootPaths':['/repo/one']},'two':{'rootPaths':['/repo/two']}}}
            (Path(home)/'.codex-global-state.json').write_text(json.dumps(state))
            db.execute('CREATE TABLE threads(id,project_id)')
            replace_projects(db, state['local-projects'])
            rows=[{'id':'unassigned','cwd':'/worktree/branch'}]
            with patch('carryon.sessions.catalog.subprocess.run') as run:
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
            replace_projects(db, state['local-projects'])
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
            self.assertEqual(result['ambiguous']['nativeProjectId'], 'shared')
            self.assertTrue(result['recent']['projectless'])
            self.assertNotIn('nativeProjectId', result['recent'])

    def test_shared_root_matches_desktop_preference_without_overriding_membership(self):
        with tempfile.TemporaryDirectory() as home, closing(sqlite3.connect(':memory:')) as db:
            projects = {
                'bundle': {'rootPaths': ['/other', '/repo'], 'createdAt': 1},
                'single': {'rootPaths': ['/repo'], 'createdAt': 9},
            }
            state = {'local-projects': projects, 'projectless-thread-ids': ['recent'],
                     'thread-project-assignments': {'assigned': {'projectId': 'bundle'}}}
            path = Path(home) / '.codex-global-state.json'
            db.execute('CREATE TABLE threads(id,project_id)')
            replace_projects(db, state['local-projects'])
            db.executemany('INSERT INTO threads VALUES(?,?)', [('native','bundle'), ('assigned','bundle')])
            def classify():
                path.write_text(json.dumps(state))
                replace_projects(db, state['local-projects'])
                rows = [{'id': tid, 'cwd': '/repo'} for tid in ('inferred','assigned','native','recent')]
                Catalog(home).classify_projects(db, rows)
                result = {r['id']: r for r in rows}
                self.assertEqual(result['assigned']['nativeProjectId'], 'bundle')
                self.assertEqual(result['native']['nativeProjectId'], 'bundle')
                self.assertTrue(result['recent']['projectless'])
                self.assertNotIn('nativeProjectId', result['recent'])
                return result['inferred']['nativeProjectId']
            self.assertEqual(classify(), 'single')
            projects['primary'] = {'rootPaths': ['/repo','/third'], 'createdAt': 10}
            del projects['single']
            self.assertEqual(classify(), 'primary')
            projects['earlier'] = {'rootPaths': ['/repo','/fourth'], 'createdAt': 2}
            self.assertEqual(classify(), 'earlier')
            projects['z-tie'] = {'rootPaths': ['/repo','/fifth'], 'createdAt': 2}
            self.assertEqual(classify(), 'z-tie')
            state['local-projects'] = dict(reversed(list(projects.items())))
            self.assertEqual(classify(), 'z-tie')

    def test_display_name_and_internal_thread_filter(self):
        with tempfile.TemporaryDirectory() as home:
            with closing(sqlite3.connect(Path(home) / 'state_5.sqlite')) as db:
                db.execute('CREATE TABLE threads(id,title,name,cwd,updated_at,created_at,history_mode,archived,source,thread_source)')
                replace_projects(db, {})
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
                replace_projects(db, state['local-projects'])
                examples = [
                    ('explicit', '/workspace/project', None, True),
                    ('unassigned', '/temporary/xue', None, True),
                    ('similar-name', '/workspace/project-other', None, True),
                    ('assigned', '/worktrees/branch', 'saved', False),
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
                replace_projects(db, {'native-saved': {'rootPaths': [str(repo)]}})
                for tid, cwd in [('main', repo), ('branch', tree), ('child', repo / 'src')]:
                    db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?)', (tid, tid, tid, str(cwd), 1, 1, 'legacy', 0, 'vscode', 'user'))
                db.commit()
            rows = Catalog(home).list()
            self.assertEqual({row['projectRoot'] for row in rows}, {str(repo)})
            self.assertFalse(any(row['projectless'] for row in rows))

    def test_native_project_store_ignores_conflicting_legacy_ids_and_metadata(self):
        with tempfile.TemporaryDirectory() as home, closing(sqlite3.connect(':memory:')) as db:
            (Path(home) / '.codex-global-state.json').write_text(json.dumps({
                'local-projects': {'desktop-id': {'name': 'Old name', 'rootPaths': ['/repo']}},
                'thread-project-assignments': {'thread': {'projectId': 'desktop-id'}},
            }))
            db.execute('CREATE TABLE threads(id,project_id)')
            replace_projects(db, {'native-id': {'name': 'Current name', 'rootPaths': ['/repo', '/api']}})
            rows = [{'id': 'thread', 'cwd': '/repo'}]
            Catalog(home).classify_projects(db, rows)
            self.assertEqual(rows[0]['nativeProjectId'], 'native-id')
            self.assertEqual(rows[0]['projectName'], 'Current name')
            self.assertEqual(rows[0]['projectRoots'], ['/repo', '/api'])

    def test_native_project_catalog_works_without_desktop_json_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as home:
            from native_project_fixture import write_projects
            write_projects(home, {'native-id': {'name': 'Current', 'rootPaths': ['/first', '/second']}})
            catalog = Catalog(home)
            self.assertEqual(catalog.projects()[0]['rootPaths'], ['/first', '/second'])
            with catalog.connection() as conn:
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("UPDATE projects SET name='changed'")
            self.assertEqual(catalog.projects()[0]['name'], 'Current')
