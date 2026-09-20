"""Workspace-owned Codex app-server over private stdio JSON-RPC."""
import copy
import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from .ipc import IPCError
from .events import Events
from .history_cache import NativeSnapshot
from .usage import executable


def project(thread, requests=()):
    turns = []
    for value in thread.get('turns', []):
        items = value.get('items', [])
        inputs = [part for item in items if item.get('type') == 'userMessage' for part in item.get('content', [])]
        turns.append({**value, 'turnId':value['id'], 'params':{'input':inputs},
                      'items':[item for item in items if item.get('type') != 'userMessage']})
    return NativeSnapshot({'id':thread['id'], 'title':thread.get('name') or thread.get('preview',''),
        'cwd':thread.get('cwd',''), 'turns':turns, 'requests':list(requests),
        'threadRuntimeStatus':thread.get('status', {'type':'notLoaded'}),
        'latestThreadSettings':{'model':thread.get('model'), 'reasoningEffort':thread.get('reasoningEffort')}})


class AppServer:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.process = None
        self.authenticated = False
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.pending = {}
        self.snapshots = {}
        self.threads = {}
        self.requests = {}
        self.following = {}
        self.watchers = {}
        self.events = Events(self)
        self.on_change = lambda: None
        self.on_read = lambda tid: None

    @property
    def connected(self):
        return self.process is not None and self.process.poll() is None

    def connect(self):
        self.process = subprocess.Popen([executable(), 'app-server', '--listen', 'stdio://'],
            cwd=self.home, env=dict(os.environ, CODEX_HOME=str(self.home)), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read, daemon=True, name='codex-app-server').start()
        try:
            self.rpc('initialize', {'clientInfo':{'name':'carryon','version':'0.2.2'},
                                   'capabilities':{'experimentalApi':True}})
            self._write({'method':'initialized'})
            self.authenticated = self.rpc('account/read', {'refreshToken':False}).get('account') is not None
        except Exception:
            self.close(); raise

    def _write(self, message):
        with self.write_lock:
            if not self.connected: raise IPCError('Codex app-server 已断开')
            try:
                self.process.stdin.write(json.dumps(message).encode()+b'\n')
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                raise IPCError('Codex app-server 写入失败', uncertain=True) from error

    def rpc(self, method, params, before_send=None, timeout=20):
        ident = str(uuid.uuid4())
        waiter = {'event':threading.Event()}
        with self.lock: self.pending[ident] = waiter
        try:
            send = lambda: self._write({'id':ident,'method':method,'params':params})
            if before_send: before_send(send)
            else: send()
            if not waiter['event'].wait(timeout): raise IPCError('Codex app-server 响应超时；请核对结果', uncertain=True)
            value = waiter.get('response', {})
            if 'error' in value: raise IPCError(str(value['error'].get('message','Codex 请求失败')))
            if 'result' not in value: raise IPCError('Codex app-server 已断开', uncertain=True)
            return value['result']
        finally:
            with self.lock: self.pending.pop(ident, None)

    def _publish(self, tid):
        if tid in self.threads:
            self.snapshots[tid] = project(self.threads[tid], [r for r in self.requests.values() if r['params'].get('threadId') == tid])

    def _read(self):
        process = self.process
        try:
            while True:
                line = process.stdout.readline(32*1024*1024+1)
                if not line: break
                if len(line) > 32*1024*1024: raise ValueError('app-server response too large')
                message = json.loads(line)
                if 'method' not in message:
                    with self.lock:
                        waiter = self.pending.get(message.get('id'))
                        if waiter: waiter.update(response=message); waiter['event'].set()
                    continue
                params, method = message.get('params', {}), message['method']
                tid = params.get('threadId')
                with self.lock:
                    if method == 'account/updated': self.authenticated = params.get('authMode') is not None
                    if 'id' in message:
                        self.requests[message['id']] = message
                    elif method == 'serverRequest/resolved':
                        self.requests.pop(params.get('requestId'), None)
                    elif method == 'thread/started':
                        thread = params['thread']; tid = thread['id']; self.threads[tid] = thread
                        self.events.catalog_revision += 1
                    elif tid in self.threads:
                        thread = copy.deepcopy(self.threads[tid]); self.threads[tid] = thread
                        if method == 'thread/status/changed': thread['status'] = params['status']
                        elif method in ('turn/started','turn/completed'):
                            turn = params['turn']; old = next((t for t in thread['turns'] if t['id'] == turn['id']), None)
                            if old: old.update({**turn, 'items':turn.get('items') or old.get('items',[])})
                            else: thread['turns'].append(turn)
                        elif method in ('item/started','item/completed','item/agentMessage/delta'):
                            turn = next((t for t in thread['turns'] if t['id'] == params.get('turnId')), None)
                            if turn is not None:
                                item = params.get('item')
                                item_id = item['id'] if item else params.get('itemId')
                                old = next((i for i in turn['items'] if i['id'] == item_id), None)
                                if item:
                                    if old is not None: old.update(item)
                                    else: turn['items'].append(item)
                                elif old is not None: old['text'] = old.get('text','')+params.get('delta','')
                    self._publish(tid)
                self.on_change()
        except (OSError, ValueError, KeyError):
            pass
        finally:
            with self.lock:
                for waiter in self.pending.values(): waiter['event'].set()
                if self.process is process:
                    self.process = None
                    if process.poll() is None: process.terminate()
            self.on_change()

    def snapshot(self, tid):
        with self.lock:
            state = self.snapshots.get(tid)
            if state is not None and state['threadRuntimeStatus'].get('type') != 'notLoaded':
                return 'app-server', state
        result = self.rpc('thread/resume', {'threadId':tid})
        with self.lock:
            self.threads[tid] = result['thread']
            self.following[tid] = 'app-server'
            self._publish(tid)
            return 'app-server', self.snapshots[tid]

    sidebar_snapshot = snapshot

    def current(self, tid):
        with self.lock: return self.snapshots.get(tid)

    def watch(self, tid):
        with self.lock: self.watchers[tid] = self.watchers.get(tid,0)+1

    def unwatch(self, tid):
        with self.lock:
            self.watchers[tid] = max(0,self.watchers.get(tid,0)-1)

    def start(self, thread_id, text, owner, client_message_id, before_send, images=None):
        if not self.authenticated: raise IPCError('请在电脑上登录此工作区的 Codex 模型账号')
        inputs = ([{'type':'text','text':text,'text_elements':[]}] if text else []) + [{'type':'image','url':url} for url in images or []]
        return self.rpc('turn/start', {'threadId':thread_id,'input':inputs,'clientUserMessageId':client_message_id}, before_send)['turn']

    def request(self, method, params, version=0, target=None, before_send=None, timeout_ms=15000):
        tid = params.get('conversationId')
        name = method.removeprefix('thread-follower-')
        if name == 'interrupt-turn':
            result = self.rpc('turn/interrupt', {'threadId':tid,'turnId':params['expectedTurnId']}, before_send)
        elif name == 'steer-turn':
            state = self.current(tid)
            active = next(t for t in reversed(state['turns']) if t['status'] == 'inProgress')
            result = self.rpc('turn/steer', {'threadId':tid, 'expectedTurnId':active['turnId'], 'input':params['input']}, before_send)
        elif name == 'compact-thread':
            result = self.rpc('thread/compact/start', {'threadId':tid}, before_send)
        elif name == 'update-thread-settings':
            settings = params['threadSettings']
            allowed = {'threadId','model','reasoningEffort','approvalPolicy','sandboxMode','serviceTier'}
            if set(settings)-allowed: raise IPCError('此设置尚不受 Codex app-server 支持')
            state = self.current(tid)
            if state['threadRuntimeStatus'].get('type') != 'idle': raise IPCError('请在任务空闲时修改设置')
            overrides = {k:v for k,v in settings.items() if k in ('model','approvalPolicy','serviceTier')}
            if 'sandboxMode' in settings: overrides['sandbox'] = settings['sandboxMode']
            if 'reasoningEffort' in settings: overrides['config'] = {'model_reasoning_effort':settings['reasoningEffort']}
            result = self.rpc('thread/resume', {'threadId':tid, **overrides}, before_send)
            with self.lock:
                self.threads[tid] = result['thread']; self._publish(tid)
        elif name == 'edit-last-user-turn':
            self.rpc('thread/rollback', {'threadId':tid,'numTurns':1}, before_send)
            try:
                result = self.rpc('turn/start', {'threadId':tid,'input':[{'type':'text','text':params['message'],'text_elements':[]}]}, before_send)
            except IPCError as error:
                raise IPCError('历史已回退，重发结果需核对：'+str(error), uncertain=True) from error
        elif name == 'set-queued-follow-ups-state':
            raise IPCError('当前 Codex app-server 不提供排队编辑接口，请在任务空闲后发送')
        elif name in ('command-approval-decision','file-approval-decision','permissions-request-approval-response','submit-user-input','submit-mcp-server-elicitation-response'):
            ident = params['requestId']
            with self.lock:
                request = self.requests.get(ident)
                if request is None or request['params'].get('threadId') != tid: raise IPCError('审批请求已失效')
            response = params.get('response', {'decision':params.get('decision')})
            write = lambda: self._write({'id':ident,'result':response})
            if before_send: before_send(write)
            else: write()
            result = {}
        else:
            raise IPCError('此操作尚不受 Codex app-server 支持')
        return {'result':result}

    def close(self):
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
            for stream in (process.stdin,process.stdout):
                if stream: stream.close()
