"""CarryOn bridge backed by one isolated app-server process."""
import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path
from .app_server import AppServer, project
from .bridge import Bridge
from .catalog import Catalog, valid_id
from .errors import BridgeError
from .ipc import IPCError


class AppServerCatalog(Catalog):
    def __init__(self, home):
        super().__init__(home)
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
        result, cursor = [], None
        while True:
            page = ipc.rpc('thread/list', {'limit':100, 'cursor':cursor, 'archived':False})
            result.extend(self.row(thread) for thread in page['data'] if not thread.get('parentThreadId'))
            cursor = page.get('nextCursor')
            if not cursor: break
        if search: result = [row for row in result if search.casefold() in (row['title']+' '+row['cwd']).casefold()]
        return result[offset:offset+limit]


class AppServerBridge(Bridge):
    def __init__(self, home, journal):
        catalog = AppServerCatalog(home)
        super().__init__(home, catalog, journal, ipc_factory=AppServer)
        catalog.bridge = self

    def status(self):
        return {**super().status(), 'protocol':'codex-app-server', 'backend':'app-server', 'supportsDirectCreation':True, 'accountAuthenticated':bool(self.ipc and self.ipc.authenticated)}

    def submit(self, kind, request_id, prompt, thread_id=None, images=None, source=None, authorize=None, parent_id=None, creation_project=None):
        if kind != 'create':
            return super().submit(kind, request_id, prompt, thread_id, images, source, authorize, parent_id, creation_project)
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id): raise ValueError('requestId 无效')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>16000: raise ValueError('请输入 1–16000 字符的消息')
        if images: raise ValueError('请先创建会话，再发送图片')
        fingerprint = hashlib.sha256(json.dumps(['create',prompt,creation_project],sort_keys=True).encode()).hexdigest()
        ipc, generation = self.require()
        if not ipc.authenticated: raise BridgeError('请在电脑上登录此工作区的 Codex 模型账号',409)
        with self.lock:
            if authorize: authorize()
            previous = self.journal.get(request_id)
            if previous:
                if previous['fingerprint'] != fingerprint: raise BridgeError('requestId 已用于不同内容')
                return previous
            job = {'id':request_id,'kind':'create','threadId':'','state':'preparing','created':time.time(),
                   'fingerprint':fingerprint,'clientMessageId':str(uuid.uuid4()), **(source or {})}
            self.journal.insert(job)
        threading.Thread(target=self._create, args=(ipc,generation,job,prompt,authorize),daemon=True).start()
        return job

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

    def _create(self, ipc, generation, job, prompt, authorize):
        sent = False
        def guarded(write):
            nonlocal sent
            with self.lock:
                self.check_generation(ipc,generation)
                if authorize: authorize()
                self.journal.update(job['id'],state='dispatching')
                sent = True; write()
        try:
            result = ipc.rpc('thread/start', {'cwd':str(self.catalog.home.parent/'projects'),
                    'approvalPolicy':'on-request','sandbox':'workspace-write'}, guarded)
            tid = result['thread']['id']
            self.journal.update(job['id'],threadId=tid,createdThreadId=tid)
            with ipc.lock:
                ipc.threads[tid]=result['thread']; ipc._publish(tid)
            turn = ipc.start(tid,prompt,'app-server',job['clientMessageId'],guarded)
            self.journal.update(job['id'],state='accepted',turnId=turn['id'],createdThreadId=tid,evidence='app-server-thread-start')
            self.workspace.catalog_refresh()
            self.notify()
        except Exception as error:
            uncertain = sent and not (isinstance(error,IPCError) and not error.uncertain)
            self.journal.update(job['id'],state='uncertain' if uncertain else 'failed',error=str(error))
