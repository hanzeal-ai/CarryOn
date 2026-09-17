"""Exercise the installed Codex with two private homes and a local fake model.

No real prompts, credentials, or model API calls are used.
"""
import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from carryon.app_server import AppServer
from carryon.catalog import Catalog
from carryon.ipc import IPCError


class Model(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        item={'id':'msg_fixture','type':'message','role':'assistant','status':'completed',
              'content':[{'type':'output_text','text':'fixture response','annotations':[]}]}
        response={'id':'resp_fixture','object':'response','status':'completed','output':[item],
                  'usage':{'input_tokens':10,'output_tokens':3,'total_tokens':13}}
        events=[{'type':'response.created','response':{**response,'status':'in_progress','output':[]}},
                {'type':'response.output_item.added','output_index':0,'item':{**item,'status':'in_progress','content':[]}},
                {'type':'response.output_text.delta','item_id':item['id'],'output_index':0,'content_index':0,'delta':'fixture response'},
                {'type':'response.output_item.done','output_index':0,'item':item},
                {'type':'response.completed','response':response}]
        body=''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


def wait_until(check):
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        if check(): return
        time.sleep(.05)
    raise AssertionError('condition did not become true')


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Model)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='carryon-appserver-regression-') as temporary:
        root=Path(temporary).resolve();source=root/'source';source.mkdir()
        (source/'config.toml').write_text('model="gpt-5.5"\nmodel_provider="fixture"\n[model_providers.fixture]\nname="Local fixture"\nbase_url="http://127.0.0.1:'+str(server.server_port)+'/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
        with patch.dict(os.environ,{'CODEX_HOME':str(source),'CARRYON_REGISTRY_DIR':str(root/'registry')}):
            a=AppServer(root/'workspace a/codex-home');b=AppServer(root/'workspace b/codex-home')
            try:
                a.connect();b.connect();assert a.account_ready and b.account_ready
                pid_a,pid_b=a.process.pid,b.process.pid;assert pid_a!=pid_b
                duplicate=AppServer(a.home)
                try:
                    duplicate.connect()
                    raise AssertionError('duplicate home connected')
                except BlockingIOError: pass
                assert a.connected
                result=a.rpc('thread/start',{'cwd':str(root)})
                tid=result['thread']['id']
                a.start(tid,'Return fixture response only','app-server','fixture-input',lambda write:write())
                wait_until(lambda: any(t['status'] in ('completed','failed') for t in (a.current(tid) or {}).get('turns',[])))
                state=a.current(tid);assert state['turns'][-1]['status']=='completed', state['turns'][-1].get('error')
                assert any(i.get('text')=='fixture response' for i in state['turns'][-1]['items'])
                wait_until(lambda: bool(Catalog(a.home, independent=True).list()))
                assert Catalog(b.home, independent=True).list()==[]
                assert b.rpc('thread/loaded/list',{})['data']==[]
                try:
                    b.snapshot(tid)
                    raise AssertionError('other workspace read a thread')
                except IPCError: pass
                a.close();assert b.connected and b.process.pid==pid_b
                a.connect();assert a.process.pid!=pid_a
                _,restored=a.snapshot(tid)
                assert any(i.get('text')=='fixture response' for t in restored['turns'] for i in t['items'])
                assert len(Catalog(a.home, independent=True).list())==1
                process=a.process;process.kill();process.wait(timeout=3)
                wait_until(lambda:not a.connected)
                a.close();a.connect();assert a.connected and b.connected
                print(json.dumps({'passed':True,'checks':['distinct processes','exclusive home lock','first turn','streamed response','catalog isolation','cross-home read refused','stop isolation','restart restores history','crash reconnect']},ensure_ascii=False))
            finally:a.close();b.close()
            from carryon.cli import main as cli, call
            homes=[root/'service a',root/'service b']
            try:
                for home in homes:
                    with redirect_stdout(io.StringIO()):
                        assert cli(['start','--state-dir',str(home),'--port','0'])==0
                    assert call(home,'/status')['protocol']=='codex-app-server'
                job=call(homes[0],'/threads',{'requestId':'first-api-create','prompt':'Return fixture response only'})
                wait_until(lambda:call(homes[0],'/jobs/'+job['id'])['state'] in ('completed','failed','uncertain'))
                created=call(homes[0],'/jobs/'+job['id']);assert created['state']=='completed',created
                tid=created['createdThreadId']
                wait_until(lambda:call(homes[0],'/threads/'+tid+'/history')['status']['state']=='idle')
                history=call(homes[0],'/threads/'+tid+'/history')
                assert any(m.get('text')=='fixture response' for m in history['messages'])
                assert call(homes[1],'/threads')['threads']==[]
                assert call(homes[1],'/projects')['projects'][0]['canCreate']
                again=call(homes[0],'/threads',{'requestId':'first-api-create','prompt':'Return fixture response only'})
                assert again['createdThreadId']==tid
                print(json.dumps({'passed':True,'checks':['CarryOn startup','first API creation without controller','API history','API isolation','empty workspace creation entry','idempotent create']}))
            finally:
                for home in homes:
                    with redirect_stdout(io.StringIO()):cli(['stop','--state-dir',str(home)])
    server.shutdown();server.server_close()


if __name__=='__main__':main()
