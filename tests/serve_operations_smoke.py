"""Isolated browser fixture; never connects to Codex. Run from project root."""
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carryon.bridge import Bridge
from carryon.events import Events
from carryon.queue import message
from carryon.server import Handler, Server
from carryon.store import Journal
from test_operations import IPC, T, state

U='22222222-2222-4222-8222-222222222222'


class FixtureIPC(IPC):
    def __init__(self, path):
        import threading
        super().__init__(path)
        self.lock=threading.RLock();self.events=Events(self)
        self.states={T:state('active'),U:state()};self.states[U]['id']=U
        self.states[T]['title']='模拟执行会话';self.states[U]['title']='模拟空闲会话'
        self.states[T]['requests']=[
            {'id':1,'method':'item/commandExecution/requestApproval','params':{
                'command':'echo smoke','proposedExecpolicyAmendment':['echo'],
                'proposedNetworkPolicyAmendments':[{'host':'example.test','action':'allow'}]}},
            {'id':2,'method':'item/permissions/requestApproval','params':{'permissions':{'fileSystem':{'read':['/tmp']}}}}]
        self.events.queues[T]=[message('first',state()),message('second',state())]
        self.events.queues[T][0]['pausedReason']='模拟暂停'
    def current(self, tid):return copy.deepcopy(self.states[tid])
    def snapshot(self, tid):return 'owner',self.current(tid)
    def watch(self, tid):pass
    def unwatch(self, tid):pass
    def request(self, method, params, version, owner, guard):
        guard(lambda:self.calls.append((method,params,version,owner)))
        tid=params['conversationId'];s=self.states[tid]
        if method.endswith('set-queued-follow-ups-state'):
            self.events.queues[tid]=copy.deepcopy(params['state'][tid])
        if method.endswith('update-thread-settings'):
            s.setdefault('latestThreadSettings',{}).update(params['threadSettings'])
        if 'requestId' in params:
            s['requests']=[r for r in s['requests'] if r['id']!=params['requestId']]
        self.on_change()
        return {'result':{'ok':True}}


class FixtureCatalog:
    def get(self, tid):
        if tid not in (T,U):raise ValueError('unknown fixture thread')
        return {'id':tid,'title':'模拟执行会话' if tid==T else '模拟空闲会话','cwd':'/tmp/smoke'}
    def list(self,*args):return [self.get(T),self.get(U)]
    def queued(self, tid):return []


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as d:
        b=Bridge('unused',FixtureCatalog(),Journal(Path(d)/'jobs.sqlite'),FixtureIPC);b.enable()
        s=Server(('127.0.0.1',8770),Handler);s.bridge=b;s.token='carryon-local-smoke';s.allowed_hosts={'127.0.0.1:8770'}
        print('Isolated fixture: http://127.0.0.1:8770/example.html#token=carryon-local-smoke',flush=True)
        try:s.serve_forever()
        finally:b.disable();s.server_close()
