"""Native project-store fixtures; never writes a user's Codex home."""
import sqlite3
from contextlib import closing
from pathlib import Path


def replace_projects(conn, projects):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',
            position INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS project_roots (
            project_id TEXT NOT NULL, position INTEGER NOT NULL, path TEXT NOT NULL,
            PRIMARY KEY(project_id, position));
        DELETE FROM project_roots;
        DELETE FROM projects;
    ''')
    for position, (pid, project) in enumerate(projects.items()):
        conn.execute('INSERT INTO projects VALUES(?,?,?,?,?,?)',
                     (pid, project.get('name', ''), '{}', position, project.get('createdAt', 0), project.get('updatedAt', 0)))
        conn.executemany('INSERT INTO project_roots VALUES(?,?,?)',
                         [(pid, index, root) for index, root in enumerate(project.get('rootPaths', []))])
    conn.commit()


def write_projects(home, projects):
    with closing(sqlite3.connect(Path(home) / 'state_5.sqlite')) as conn:
        replace_projects(conn, projects)
