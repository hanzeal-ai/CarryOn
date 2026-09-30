"""Read-only local history projection. Never resumes or writes a Codex database."""
import json
import re
import sqlite3
import threading
import subprocess
from pathlib import Path
from contextlib import contextmanager


ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


def valid_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("无效的会话 ID")
    return value


class Catalog:
    def __init__(self, home, independent=False):
        self.home = Path(home).resolve()
        self.independent = independent
        self.lock = threading.Lock()
        self.rollout_cache = {}

    def children(self, parent_id):
        from carryon.sessions.subagents import spawn_source
        valid_id(parent_id)
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM threads WHERE archived=0 ORDER BY created_at, id").fetchall()
        children = {}
        for record in rows:
            row = dict(record)
            parent = spawn_source(row).get('parent_thread_id')
            if isinstance(parent, str): children.setdefault(parent, []).append(row)
        result, pending, seen = [], [parent_id], {parent_id}
        for parent in pending:
            for row in children.get(parent, []):
                if row['id'] in seen: continue
                seen.add(row['id']); result.append(row); pending.append(row['id'])
        return result

    def rollout_index(self, thread_id):
        from carryon.sessions.rollout import RolloutIndex
        row = self.get(thread_id)
        path = Path(row['rollout_path']).resolve()
        if not path.is_relative_to(self.home):
            raise ValueError('本地会话历史不可用')
        with self.lock:
            index = self.rollout_cache.pop(thread_id, None)
            if index is None or index.path != path:
                index = RolloutIndex(row, self.home)
            self.rollout_cache[thread_id] = index
            while len(self.rollout_cache) > 8:
                self.rollout_cache.pop(next(iter(self.rollout_cache)))
            return index

    def rollout_state(self, thread_id, limit=None):
        return self.rollout_index(thread_id).snapshot(limit)

    def spawned_children(self, thread_id):
        index = self.rollout_index(thread_id)
        with index.lock:
            index.update()
            return set(index.spawned)

    @contextmanager
    def connection(self):
        choices = [p for p in self.home.glob("state_*.sqlite")
                   if re.fullmatch(r"state_\d+\.sqlite", p.name)]
        if not choices:
            raise ValueError("未找到 Codex 会话数据库")
        path = max(choices, key=lambda p: int(p.stem.split("_")[1]))
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def list(self, limit=100, offset=0, search=""):
        if self.independent and not any(self.home.glob('state_*.sqlite')):
            return []
        with self.connection() as conn:
            rows = conn.execute("""SELECT id,
                substr(COALESCE(NULLIF(name,''), NULLIF(title,''), '未命名会话'),1,120) title,
                cwd, updated_at, created_at, history_mode FROM threads
                WHERE archived=0 AND source IN ('vscode','cli','exec')
                AND COALESCE(thread_source,'user') NOT IN ('subagent','sub-agent')
                AND (COALESCE(NULLIF(name,''),title) LIKE ? OR cwd LIKE ?)
                ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
                ("%" + search + "%", "%" + search + "%", limit, offset)).fetchall()
            rows = [dict(r) for r in rows]
            self.classify_projects(conn, rows)
            return rows

    def classify_projects(self, conn, rows):
        # Desktop projectless tasks have a working directory too. A directory
        # alone does not make a task belong to a saved Codex project.
        path = self.home / '.codex-global-state.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        projectless = set(state.get('projectless-thread-ids', []))
        assignments = state.get('thread-project-assignments', {})
        roots = [Path(root).expanduser().absolute()
                 for project in state.get('local-projects', {}).values()
                 for root in project.get('rootPaths', [])]
        roots.extend(Path(root).expanduser().absolute()
                     for root in state.get('electron-saved-workspace-roots', []))
        columns = {r[1] for r in conn.execute('PRAGMA table_info(threads)')}
        native = dict(conn.execute('SELECT id,project_id FROM threads')) if 'project_id' in columns else {}
        projects = state.get('local-projects', {})
        git_roots = {}
        def repository(path):
            key = str(path)
            if key not in git_roots:
                try:
                    result = subprocess.run(['git', '-C', key, 'rev-parse', '--path-format=absolute', '--git-common-dir'], capture_output=True, text=True, timeout=2)
                    git_roots[key] = Path(result.stdout.strip()).resolve() if result.returncode == 0 else None
                except (OSError, subprocess.TimeoutExpired):
                    git_roots[key] = None
            return git_roots[key]
        for row in rows:
            tid = row['id']
            if native.get(tid):
                row['projectless'] = False
            elif tid in projectless:
                row['projectless'] = True
            elif assignments.get(tid, {}).get('projectId'):
                row['projectless'] = False
            else:
                cwd = Path(row['cwd']).expanduser().absolute() if row.get('cwd') else None
                row['projectless'] = not (cwd and any(cwd.is_relative_to(root) for root in roots))
            cwd = Path(row['cwd']).expanduser().absolute() if row.get('cwd') else None
            pid = native.get(tid) or assignments.get(tid, {}).get('projectId')
            if tid in projectless and not native.get(tid):
                continue
            assigned = projects.get(pid, {}).get('rootPaths', []) if native.get(tid) or tid not in projectless else []
            root = Path(assigned[0]).expanduser().absolute() if assigned else None
            if root is None and cwd and not pid:
                matches = [r for r in roots if cwd.is_relative_to(r)]
                root = max(matches, key=lambda r: len(r.parts)) if matches else None
                candidates = [root] if root is not None else []
                if root is None:
                    common = repository(cwd)
                    candidates = [r for r in roots if common and repository(r) == common]
                    root = candidates[0] if candidates else None
            if not pid and root is not None:
                owners = [key for key, project in projects.items()
                          if any(Path(p).expanduser().absolute() in candidates for p in project.get('rootPaths', []))]
                if len(owners) == 1:
                    pid = owners[0]
                elif owners and len(set(candidates)) == 1:
                    # Match Codex's sidebar preference for projects sharing one root:
                    # single-root, primary-root match, earlier creation, then larger ID.
                    # Distinct roots sharing a Git repository remain ambiguous.
                    def preference(key):
                        project = projects[key]
                        paths = project.get('rootPaths', [])
                        return (len(paths) == 1,
                                Path(paths[0]).expanduser().absolute() == root,
                                -(project.get('createdAt') or 0), key)
                    pid = max(owners, key=preference)
            if pid:
                project = projects.get(pid, {})
                row['nativeProjectId'] = pid
                row['projectName'] = project.get('name') or ''
                row['projectRoots'] = [str(Path(p).expanduser().absolute()) for p in project.get('rootPaths', [])]
                if row['projectRoots']:
                    root = Path(row['projectRoots'][0])
            if root is not None:
                row['projectless'] = False
                row['projectRoot'] = str(root)
            elif pid:
                row['projectKey'] = str(pid)

    def get(self, thread_id):
        valid_id(thread_id)
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM threads WHERE id=? AND archived=0", (thread_id,)).fetchone()
            if row is None:
                raise ValueError("会话不存在或已归档")
            return dict(row)

    def side_candidates(self):
        if self.independent: return []
        data = json.loads((self.home / '.codex-global-state.json').read_text())
        bindings = data.get('electron-persisted-atom-state', {}).get('client-thread-bindings-v1', {})
        with self.connection() as conn:
            persisted = {r[0] for r in conn.execute('SELECT id FROM threads')}
        return sorted({v for v in bindings.values() if isinstance(v, str) and ID.fullmatch(v)
                       and v not in persisted}, reverse=True)[:100]

    def queued(self, thread_id):
        valid_id(thread_id)
        if self.independent: return []
        data = json.loads((self.home / '.codex-global-state.json').read_text())
        queues = data.get('queued-follow-ups', {})
        if not isinstance(queues, dict):
            raise ValueError('原生排队消息格式无法识别')
        return queues.get(thread_id, [])
