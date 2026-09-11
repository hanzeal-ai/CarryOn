import sqlite3
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
