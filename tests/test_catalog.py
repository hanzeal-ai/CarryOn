import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from connectnow.catalog import Catalog


class CatalogTests(unittest.TestCase):
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
