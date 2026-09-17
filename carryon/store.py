"""CarryOn delivery journal; no writes to Codex data."""
import json
import sqlite3
import threading
import time


class Journal:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.on_change = lambda: None
        self.conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, kind TEXT NOT NULL,
            thread_id TEXT NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL)""")
        self.conn.commit()
        for job in self.list():
            if job["state"] in ("preparing", "dispatching"):
                self.update(job["id"], state="uncertain", error="服务曾中断，请核对原会话；不会自动重发")

    def get(self, job_id):
        with self.lock:
            row = self.conn.execute("SELECT body FROM jobs WHERE id=?", (job_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, limit=None):
        with self.lock:
            if limit is not None and (type(limit) is not int or limit < 0):
                raise ValueError('Invalid journal limit')
            query = "SELECT body FROM jobs ORDER BY created DESC"
            rows = self.conn.execute(query) if limit is None else self.conn.execute(query + " LIMIT ?", (limit,))
            return [json.loads(r[0]) for r in rows]

    def insert(self, job):
        with self.lock:
            self.conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", (
                job["id"], job["fingerprint"], job["kind"], job["threadId"], job["state"],
                json.dumps(job, ensure_ascii=False), job["created"], job["created"]))
            self.conn.commit()
        self.on_change()

    def update(self, job_id, *, expected=None, **fields):
        """Apply delayed evidence only if the full observed job is still current."""
        with self.lock:
            job = self.get(job_id)
            if job is None or (expected is not None and job != expected):
                return job
            if all(job.get(key) == value for key, value in fields.items()):
                return job
            original = json.dumps(job, ensure_ascii=False)
            job.update(fields, updated=time.time())
            cursor = self.conn.execute("UPDATE jobs SET state=?,thread_id=?,body=?,updated=? WHERE id=? AND body=?", (
                job["state"], job["threadId"], json.dumps(job, ensure_ascii=False), job["updated"], job_id, original))
            self.conn.commit()
            if not cursor.rowcount:
                return self.get(job_id)
        self.on_change()
        return job
