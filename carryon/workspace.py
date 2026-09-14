"""Device-scoped project/activity projection and persistent reader notifications."""
import hashlib
import json
import threading
import time
from pathlib import Path
from .catalog import valid_id
from .contracts import digest
from .operations import turns, controls
from .thread_status import project_status

KINDS=('message','done','failed','approval')


def project_identity(cwd, projectless=False):
    path=str(Path(cwd).expanduser().absolute()) if cwd and not projectless else ''
    return hashlib.sha256(path.encode()).hexdigest(),Path(path).name if path else '最近'


class Workspace:
    def __init__(self,bridge):
        self.bridge=bridge;self.db=bridge.journal.conn;self.lock=bridge.journal.lock
        self.rows={};self.states={};self.fingerprints={};self.native_refs={};self.error=None;self.closed=threading.Event();self.worker=None;self.observer=None;self.revision=0
        with self.lock:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS notification_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,thread_id TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_baselines(thread_id TEXT PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_readers(reader TEXT NOT NULL,thread_id TEXT NOT NULL,sequence INTEGER NOT NULL,PRIMARY KEY(reader,thread_id));
            CREATE TABLE IF NOT EXISTS notification_preferences(reader TEXT PRIMARY KEY,body TEXT NOT NULL);
            ''');self.db.commit()

    def start(self):
        self.observer=self.bridge.open_stream()
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()

    def close(self):
        self.closed.set()
        if self.worker:self.worker.join(5)
        if self.observer:self.observer.close()

    def thread_ids(self):
        with self.lock:return set(self.rows)

    def catalog_refresh(self):
        rows=self.bridge.catalog.list(2147483647,0,'')
        with self.lock:
            fresh={r['id']:dict(r) for r in rows}
            if fresh!=self.rows:self.revision+=1
            self.rows=fresh;self.native_refs={k:v for k,v in self.native_refs.items() if k in fresh};self.error=None

    def run(self):
        next_catalog=0;revision=-1
        while not self.closed.is_set():
            try:
                if self.bridge.status()['enabled']:
                    if time.monotonic()>=next_catalog:
                        self.catalog_refresh();next_catalog=time.monotonic()+15
                    ipc,generation=self.bridge.require()
                    for tid in self.thread_ids():
                        native=ipc.current(tid)
                        if native is not None and native is not self.native_refs.get(tid):
                            with self.bridge.lock:
                                self.bridge.check_generation(ipc,generation)
                                self.observe(native)
                                self.native_refs[tid]=native
                else:
                    with self.lock:self.states={};self.fingerprints={};self.native_refs={}
            except Exception as exc:
                with self.lock:self.error='工作区状态暂不可用：'+type(exc).__name__
            with self.bridge.events:
                if revision==self.bridge.event_revision:self.bridge.events.wait(2)
                revision=self.bridge.event_revision
            self.closed.wait(.1)

    def observe(self,state):
        tid=valid_id(state['id']);native_turns=turns(state)
        last=native_turns[-1] if native_turns else {}
        terminal=last.get('status');status=project_status(state)
        failed=status['state']=='error' or terminal=='failed' and status['state']=='idle'
        requests=controls(state)['requests']
        # Only complete turns produce message/terminal events: streaming patches never spam notifications.
        candidates={}
        for turn in native_turns:
            turn_id=turn.get('turnId');end=turn.get('status')
            if not turn_id or end not in ('completed','failed','interrupted'):continue
            if end in ('completed','failed'):
                kind='done' if end=='completed' else 'failed'
                candidates[digest([tid,turn_id,kind])]={'kind':kind,'turnId':turn_id}
            for item in turn.get('items',[]):
                if item.get('type')=='agentMessage' and item.get('phase')!='analysis' and item.get('text') and item.get('id'):
                    candidates[digest([tid,turn_id,item['id'],'message'])]={'kind':'message','turnId':turn_id,'itemId':item['id']}
        for request in requests:
            key=digest([tid,request['id'],request['fingerprint'],'approval'])
            candidates[key]={'kind':'approval','requestId':request['id'],'fingerprint':request['fingerprint']}
        fingerprint=digest([candidates,status,failed])
        with self.lock:
            if self.fingerprints.get(tid)==fingerprint:return
            previous=self.db.execute('SELECT body FROM notification_baselines WHERE thread_id=?',(tid,)).fetchone()
            known=set(json.loads(previous[0])) if previous else set(candidates)
            changed=False
            for key,body in candidates.items():
                # Existing pending requests must be visible on first connection; old completed history is only a baseline.
                if key in known and (previous or body['kind']!='approval'):continue
                record={**body,'eventId':key,'threadId':tid,'created':time.time()}
                inserted=self.db.execute('INSERT OR IGNORE INTO notification_events(event_id,thread_id,kind,body) VALUES(?,?,?,?)',
                    (key,tid,body['kind'],json.dumps(record))).rowcount
                changed=changed or bool(inserted)
            self.db.execute('INSERT OR REPLACE INTO notification_baselines VALUES(?,?)',(tid,json.dumps(sorted(known|set(candidates)))))
            self.db.commit()
            self.revision+=1
            self.fingerprints[tid]=fingerprint
            self.states[tid]={'status':status,'actionable':bool(requests) or status['state']=='waiting' or failed,'failed':failed,
                              'needsConfirmation':bool(requests) or status['state']=='waiting'}
        if changed:self.bridge.notify()

    def preferences(self,reader,data=None):
        with self.lock:
            if data is not None:
                if not isinstance(data,dict) or set(data)!=set(KINDS) or any(type(v) is not bool for v in data.values()):raise ValueError('通知偏好必须包含四类布尔开关')
                self.db.execute('INSERT OR REPLACE INTO notification_preferences VALUES(?,?)',(reader,json.dumps(data)));self.db.commit()
                self.revision+=1
            row=self.db.execute('SELECT body FROM notification_preferences WHERE reader=?',(reader,)).fetchone()
            result=json.loads(row[0]) if row else dict.fromkeys(KINDS,True)
        if data is not None:self.bridge.notify()
        return result

    def read(self,reader,tid,sequence):
        valid_id(tid)
        if type(sequence) is not int or sequence<0:raise ValueError('已读序号无效')
        with self.lock:
            maximum=self.db.execute('SELECT COALESCE(MAX(sequence),0) FROM notification_events WHERE thread_id=?',(tid,)).fetchone()[0]
            if sequence>maximum:raise ValueError('已读序号超过已展示的事件')
            changed=self.db.execute('INSERT INTO notification_readers VALUES(?,?,?) ON CONFLICT(reader,thread_id) DO UPDATE SET sequence=excluded.sequence WHERE sequence<excluded.sequence',(reader,tid,sequence)).rowcount;self.db.commit()
        if changed:
            with self.lock:self.revision+=1
            self.bridge.notify()
        return {'readThrough':sequence}

    def latest_sequence(self,tid):
        with self.lock:return self.db.execute('SELECT COALESCE(MAX(sequence),0) FROM notification_events WHERE thread_id=?',(tid,)).fetchone()[0]

    def events(self,reader,after=0,limit=100):
        with self.lock:
            records=self.db.execute('SELECT sequence,body FROM notification_events WHERE sequence>? ORDER BY sequence LIMIT ?',(after,limit)).fetchall()
            rows=dict(self.rows)
        events=[]
        for record in records:
            body=json.loads(record[1]);tid=body['threadId']
            if tid in rows:
                pid,_=project_identity(rows[tid].get('projectRoot', rows[tid].get('projectKey', rows[tid].get('cwd'))),rows[tid].get('projectless',False))
                events.append({**body,'sequence':record[0],'projectId':pid,'title':rows[tid].get('title','')})
        return {'events':events,'nextSequence':records[-1][0] if records else after}

    def projection(self,reader):
        self.bridge.require()
        with self.lock:
            if self.error:raise ValueError(self.error)
            rows=list(self.rows.values());states=dict(self.states)
            preferences=self.preferences(reader)
            unread_events=self.db.execute('''SELECT e.thread_id,e.kind FROM notification_events e
                LEFT JOIN notification_readers r ON r.thread_id=e.thread_id AND r.reader=?
                LEFT JOIN notification_readers n ON n.thread_id=e.thread_id AND n.reader='native:codex'
                WHERE e.sequence>MAX(COALESCE(r.sequence,0),COALESCE(n.sequence,0)) GROUP BY e.thread_id,e.kind''',(reader,)).fetchall()
            unread={row[0] for row in unread_events}
            notified={tid for tid,kind in unread_events if preferences.get(kind,False)}
            sequences={row[0]:row[1] for row in self.db.execute('SELECT thread_id,MAX(sequence) FROM notification_events GROUP BY thread_id')}
        ipc,_=self.bridge.require();groups={};threads=[]
        for row in rows:
            tid=row['id'];native=ipc.current(tid)
            status=project_status(native)
            # Never preserve cached running/idle after a connection reset or unload.
            known=states.get(tid,{}) if native is not None else {}
            actionable=known.get('actionable',False)
            pid,name=project_identity(row.get('projectRoot', row.get('projectKey', row.get('cwd'))),row.get('projectless',False))
            thread={**row,'projectId':pid,'status':status,'actionable':actionable,'failed':known.get('failed',False),
                    'unread':tid in unread,'readSequence':sequences.get(tid,0),
                    'activity':tid in notified or (known.get('failed',False) and preferences['failed'])
                               or (known.get('needsConfirmation',False) and preferences['approval'])}
            threads.append(thread)
            group=groups.setdefault(pid,{'id':pid,'name':name,'cwd':'' if row.get('projectless') else row.get('projectRoot',row.get('cwd','')),'total':0,'waiting':0,'running':0,'unread':0,'unknown':0})
            group['total']+=1;group['waiting']+=int(actionable);group['running']+=int(status['state']=='running');group['unread']+=int(tid in unread)
            group['unknown']+=int(status['state'] in ('unknown','notLoaded','error'))
        return sorted(groups.values(),key=lambda g:(-bool(g['waiting']),-bool(g['running']),g['name'],g['id'])),threads

    def push_snapshot(self,reader,after=None):
        # Optimistic consistency avoids taking workspace -> bridge locks in reverse order.
        for _ in range(5):
            with self.lock:revision=self.revision
            _,threads=self.projection(reader)
            visible={t['id'] for t in threads if t['activity']}
            with self.lock:
                if self.revision!=revision:continue
                preferences=self.preferences(reader)
                if after is None:
                    after=self.db.execute('SELECT COALESCE(MAX(sequence),0) FROM notification_events').fetchone()[0]
                packet=self.events(reader,after,100)
                eligible=[]
                for event in packet['events']:
                    tid=event['threadId'];kind=event['kind']
                    if tid not in visible or not preferences.get(kind,False):continue
                    read=self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM notification_readers WHERE thread_id=? AND reader IN (?, 'native:codex')",(tid,reader)).fetchone()[0]
                    if event['sequence']<=read:continue
                    if kind=='message' and any(preferences[terminal] and self.db.execute(
                        'SELECT 1 FROM notification_events WHERE event_id=?',(digest([tid,event['turnId'],terminal]),)).fetchone()
                        for terminal in ('done','failed')):continue
                    eligible.append(event)
                return {'events':eligible,'nextSequence':packet['nextSequence'],'badge':len(visible)}
        raise ValueError('通知状态正在变化，请稍后重试')

    def dispatch(self,reader,method,path,data,query):
        self.bridge.require()
        data={} if data is None else data
        if not isinstance(data,dict):raise ValueError('请求体必须为对象')
        if path=='/api/notifications/push' and method=='GET':
            after=query.get('after')
            return 200,self.push_snapshot(reader,max(0,int(after[0])) if after else None)
        if path=='/api/notifications/preferences' and method in ('GET','POST'):
            return 200,{'preferences':self.preferences(reader,data if method=='POST' else None)}
        if path=='/api/notifications/read' and method=='POST':
            if data.get('threadId') not in self.thread_ids():raise ValueError('会话不可用')
            return 200,self.read(reader,data.get('threadId'),data.get('sequence'))
        limit=min(100,max(1,int(query.get('limit',['100'])[0])));offset=max(0,int(query.get('offset',['0'])[0]))
        if path=='/api/notifications' and method=='GET':return 200,self.events(reader,max(0,int(query.get('after',['0'])[0])),limit)
        if method!='GET':return 404,{'error':'接口不存在'}
        groups,threads=self.projection(reader)
        search=query.get('search',[''])[0].casefold()
        if path=='/api/projects':
            groups=[g for g in groups if search in (g['name']+' '+g['cwd']).casefold()]
            return 200,{'projects':groups[offset:offset+limit],'total':len(groups),'nextOffset':offset+limit}
        if path=='/api/activity':threads=[t for t in threads if t['activity'] and t['id']!=query.get('excludeThreadId',[''])[0]]
        elif path.startswith('/api/projects/') and path.endswith('/threads'):
            pid=path.split('/')[3];threads=[t for t in threads if t['projectId']==pid]
        elif path!='/api/workspace/threads':return 404,{'error':'接口不存在'}
        threads=[t for t in threads if search in (t.get('title','')+' '+t.get('cwd','')).casefold()]
        if path=='/api/workspace/threads' and query.get('threadId'):
            threads=[t for t in threads if t['id']==query['threadId'][0]]
        mode=query.get('filter',['all'])[0]
        if mode not in ('all','waiting','running'):raise ValueError('无效筛选')
        if mode=='waiting':threads=[t for t in threads if t['actionable']]
        if mode=='running':threads=[t for t in threads if t['status']['state']=='running']
        threads.sort(key=lambda t: (t.get('updated_at') or 0, t['id']), reverse=True)
        result={'threads':threads[offset:offset+limit],'total':len(threads),'nextOffset':offset+limit}
        if path=='/api/activity':
            current=query.get('currentThreadId',[''])[0]
            result['currentThreadIncluded']=any(t['id']==current for t in threads)
        return 200,result
