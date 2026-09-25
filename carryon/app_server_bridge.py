"""CarryOn bridge backed by one isolated app-server process."""
from .app_server import AppServer
from .bridge import Bridge
from .catalog import Catalog, valid_id
from .ipc import IPCError


class AppServerCatalog(Catalog):
    def __init__(self, home):
        super().__init__(home, independent=True)
        self.bridge = None

    def row(self, thread):
        return {'id':thread['id'], 'title':thread.get('name') or thread.get('preview') or '未命名会话',
                'cwd':thread['cwd'], 'created_at':thread['createdAt'], 'updated_at':thread['updatedAt'],
                'rollout_path':thread.get('path'), 'source':thread.get('source'),
                'projectless':True, 'projectKey':None, 'history_mode':thread.get('historyMode','legacy')}

    def get(self, tid):
        valid_id(tid)
        ipc, _ = self.bridge.require()
        return self.row(ipc.rpc('thread/read', {'threadId':tid,'includeTurns':False})['thread'])

    def list(self, limit=100, offset=0, search=''):
        ipc, _ = self.bridge.require()
        if limit <= 0:
            return []
        result, cursor = [], None
        needle = search.casefold()
        seen_cursors = set()
        while True:
            page = ipc.rpc('thread/list', {'limit':100, 'cursor':cursor, 'archived':False})
            for thread in page['data']:
                if thread.get('parentThreadId'):
                    continue
                row = self.row(thread)
                if not needle or needle in (row['title']+' '+row['cwd']).casefold():
                    result.append(row)
            if len(result) >= offset + limit:
                break
            cursor = page.get('nextCursor')
            if not cursor:
                break
            if cursor in seen_cursors:
                raise ValueError('会话分页游标重复，请重试')
            seen_cursors.add(cursor)
        return result[offset:offset+limit]


class AppServerBridge(Bridge):
    def __init__(self, home, journal):
        catalog = AppServerCatalog(home)
        super().__init__(home, catalog, journal, ipc_factory=AppServer)
        catalog.bridge = self

    def status(self):
        return {**super().status(), 'protocol':'codex-app-server', 'backend':'app-server', 'supportsDirectCreation':True, 'accountAuthenticated':bool(self.ipc and self.ipc.account_ready)}

    def _refresh_job(self, job_id):
        job = self.journal.get(job_id)
        if job and job['kind'] == 'create' and job.get('createdThreadId') and job.get('turnId'):
            if job['state'] in ('accepted','uncertain'):
                try:
                    turn = self.turn_evidence(job['threadId'],job['turnId'])
                    if turn and turn['status'] in ('completed','failed','interrupted'):
                        return self.journal.update(job_id,expected=job,state=turn['status'])
                except (ValueError,IPCError): pass
            return job
        return super()._refresh_job(job_id)
