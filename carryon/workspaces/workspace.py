"""Device-scoped project/activity projection and persistent reader notifications."""
import hashlib
import json
import threading
import time
from pathlib import Path
from carryon.sessions.catalog import valid_id
from carryon.contracts import digest
from carryon.sessions.operations import turns, controls
from carryon.sessions.thread_status import project_status
from carryon.sessions.activity_preview import preview
from carryon.sessions.history_cache import NativeSnapshot

KINDS=('message','done','failed','approval')


def project_identity(cwd, projectless=False, *, native_id=None):
    path=str(Path(cwd).expanduser().absolute()) if cwd and not projectless else ''
    if native_id and not projectless:
        return hashlib.sha256(('native-project:'+native_id).encode()).hexdigest(),Path(path).name if path else native_id
    return hashlib.sha256(path.encode()).hexdigest(),Path(path).name if path else '最近'


def row_project_identity(row):
    pid,name=project_identity(row.get('projectRoot', row.get('projectKey', row.get('cwd'))),
                              row.get('projectless',False), native_id=row.get('nativeProjectId'))
    return pid, (row.get('projectName') or name) if not row.get('projectless') else name


class Workspace:
    def __init__(self,bridge):
        self.bridge=bridge;self.db=bridge.journal.conn;self.lock=bridge.journal.lock
        self.catalog_lock=threading.Lock()
        from carryon.workspaces.sync import WorkspaceSync
        self.sync=WorkspaceSync(self)
        self.turn_candidates={};self.rows={};self.states={};self.fingerprints={};self.native_refs={};self.error=None;self.closed=threading.Event();self.worker=None;self.observer=None;self.revision=0
        with self.lock:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS notification_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,thread_id TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_baselines(thread_id TEXT PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notification_readers(reader TEXT NOT NULL,thread_id TEXT NOT NULL,sequence INTEGER NOT NULL,PRIMARY KEY(reader,thread_id));
            CREATE TABLE IF NOT EXISTS notification_preferences(reader TEXT PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS activity_cleared(reader TEXT NOT NULL,thread_id TEXT NOT NULL,sequence INTEGER NOT NULL,PRIMARY KEY(reader,thread_id));
            ''');self.db.commit()

    def start(self):
        self.observer=self.bridge.open_stream()
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()

    def close(self):
        self.closed.set()
        self.sync.close()
        if self.worker:self.worker.join(5)
        if self.observer:self.observer.close()

    def thread_ids(self):
        with self.lock:return set(self.rows)

    def desktop_reads(self):
        factory=getattr(self.bridge.catalog,'desktop_read_state',None)
        return factory() if factory else None

    def native_reader(self):
        source=self.desktop_reads()
        if source is None:return 'native:codex'
        try:return 'native:codex:'+source.identity()
        except ValueError:return 'native:unavailable'

    def read_cutoffs(self):
        with self.lock:
            return dict(self.db.execute('SELECT thread_id,MAX(sequence) FROM notification_events GROUP BY thread_id'))

    def sync_desktop_reads(self,ipc,generation,cutoffs):
        source=self.desktop_reads()
        if source is None:return 0
        identity,unread,modified=source.capture()
        pending=0
        with self.bridge.lock:
            self.bridge.check_generation(ipc,generation)
            if self.closed.is_set():raise ValueError('工作区已关闭')
            if source.identity()!=identity:raise ValueError('Codex 桌面端账号已切换，请重新刷新')
            with self.lock:
                for tid,ceiling in cutoffs.items():
                    if tid not in self.rows or tid in unread:continue
                    native=ipc.current(tid) or {}
                    if native.get('executionBackend')!='carryon-owner' and native.get('hasUnreadTurn') is True:continue
                    from carryon.desktop_ipc.read_state import event_time
                    completed={turn.get('turnId'):event_time(turn) for turn in turns(native)}
                    reader='native:codex:'+identity
                    saved=self.db.execute('SELECT sequence FROM notification_readers WHERE reader=? AND thread_id=?',(reader,tid)).fetchone()
                    saved=saved[0] if saved else 0
                    sequence=saved
                    for seq,body in self.db.execute('SELECT sequence,body FROM notification_events WHERE thread_id=? ORDER BY sequence',(tid,)):
                        if seq<=saved:continue
                        event=json.loads(body)
                        occurred=event.get('occurredAt') or completed.get(event.get('turnId'))
                        # A late-discovered old completion can be read in this
                        # pass. New/undated events need the pre-refresh fence.
                        if occurred is not None:
                            if occurred>modified:break
                        elif seq>ceiling or event.get('created',float('inf'))>modified:
                            pending+=1
                            break
                        sequence=seq
                    if sequence>saved:self.read(reader,tid,sequence)
        return pending

    def invalidate_status(self):
        with self.lock:self.revision+=1
        self.bridge.notify()

    def catalog_refresh(self):
        # Serialize background and manual reads so an older catalog cannot win.
        with self.catalog_lock:
            rows=self.bridge.catalog.list(2147483647,0,'')
            with self.lock:
                fresh={r['id']:dict(r) for r in rows}
                if fresh!=self.rows:self.revision+=1
                self.turn_candidates={k:v for k,v in self.turn_candidates.items() if k in fresh}
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
                    with self.lock:self.states={};self.fingerprints={};self.native_refs={};self.turn_candidates={}
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
        from carryon.sessions.timeline import pending_questions
        questions=pending_questions(native_turns)
        # Only complete turns produce message/terminal events: streaming patches never spam notifications.
        candidates={}
        cached=self.turn_candidates.get(tid, {}) if isinstance(state, NativeSnapshot) else {}
        next_cache={}
        for turn in native_turns:
            turn_id=turn.get('turnId');end=turn.get('status')
            if not turn_id or end not in ('completed','failed','interrupted'):continue
            previous=cached.get(turn_id)
            if previous is not None and previous[0] is turn:
                events=previous[1]
            else:
                events={}
                if end in ('completed','failed'):
                    kind='done' if end=='completed' else 'failed'
                    events[digest([tid,turn_id,kind])]={'kind':kind,'turnId':turn_id}
                for item in turn.get('items',[]):
                    if item.get('type')=='agentMessage' and item.get('phase')!='analysis' and item.get('text') and item.get('id'):
                        events[digest([tid,turn_id,item['id'],'message'])]={'kind':'message','turnId':turn_id,'itemId':item['id']}
            candidates.update(events)
            if isinstance(state, NativeSnapshot):next_cache[turn_id]=(turn,events)
        self.turn_candidates[tid]=next_cache
        for request in requests:
            key=digest([tid,request['id'],request['fingerprint'],'approval'])
            candidates[key]={'kind':'approval','requestId':request['id'],'fingerprint':request['fingerprint']}
        for question in questions:
            key=digest([tid,question['id'],'question'])
            candidates[key]={'kind':'approval','turnId':question['turnId'],'itemId':question['itemId'],'questionId':question['id']}
        activity_kind=('approval' if any(r['action'] in ('command-approval','file-approval','permissions-approval') for r in requests)
                       else 'question' if requests or questions else 'failed' if failed
                       else 'completed' if terminal=='completed' else 'other')
        activity_preview=preview(last,activity_kind,requests=requests,questions=questions)
        fingerprint=digest([candidates,status,failed,activity_preview])
        with self.lock:
            if self.fingerprints.get(tid)==fingerprint:return
            previous=self.db.execute('SELECT body FROM notification_baselines WHERE thread_id=?',(tid,)).fetchone()
            known=set(json.loads(previous[0])) if previous else set(candidates)
            for key,body in candidates.items():
                # Existing pending requests must be visible on first connection; old completed history is only a baseline.
                if key in known and (previous or body['kind']!='approval'):continue
                event_turn=next((t for t in native_turns if t.get('turnId')==body.get('turnId')),last)
                event_kind=(activity_kind if body['kind']=='approval' else 'failed' if event_turn.get('status')=='failed'
                            else 'completed' if event_turn.get('status')=='completed' else 'other')
                event_preview=preview(event_turn,event_kind,requests=requests,questions=questions)
                record={**body,'eventId':key,'threadId':tid,'created':time.time(),'preview':event_preview}
                from carryon.desktop_ipc.read_state import event_time
                occurred=event_time(event_turn)
                if occurred is not None and body['kind']!='approval':record['occurredAt']=occurred
                self.db.execute('INSERT OR IGNORE INTO notification_events(event_id,thread_id,kind,body) VALUES(?,?,?,?)',
                    (key,tid,body['kind'],json.dumps(record)))
            self.db.execute('INSERT OR REPLACE INTO notification_baselines VALUES(?,?)',(tid,json.dumps(sorted(known|set(candidates)))))
            self.db.commit()
            self.revision+=1
            self.fingerprints[tid]=fingerprint
            self.states[tid]={'status':status,'actionable':bool(requests or questions) or status['state']=='waiting' or failed,'failed':failed,
                              'needsConfirmation':bool(requests or questions) or status['state']=='waiting',
                              'activityKind':activity_kind,'activityPreview':activity_preview}
        # Runtime-only changes also invalidate project counts and list statuses.
        self.bridge.notify()

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

    def clear_read(self,reader,activity_owner=None):
        # Advance only through already read events. Never delete events or session data.
        with self.lock:
            self.db.execute('''INSERT INTO activity_cleared(reader,thread_id,sequence)
                SELECT ?,e.thread_id,MAX(e.sequence) FROM notification_events e
                LEFT JOIN notification_readers r ON r.thread_id=e.thread_id AND r.reader=?
                LEFT JOIN notification_readers n ON n.thread_id=e.thread_id AND n.reader=?
                GROUP BY e.thread_id
                HAVING MAX(e.sequence)<=MAX(COALESCE(r.sequence,0),COALESCE(n.sequence,0))
                ON CONFLICT(reader,thread_id) DO UPDATE SET sequence=MAX(sequence,excluded.sequence)''',(activity_owner or reader,reader,self.native_reader()))
            self.db.commit();self.revision+=1
        self.bridge.notify()
        return {'cleared':True}

    def events(self,reader,after=0,limit=100):
        with self.lock:
            records=self.db.execute('SELECT sequence,body FROM notification_events WHERE sequence>? ORDER BY sequence LIMIT ?',(after,limit)).fetchall()
            rows=dict(self.rows)
        events=[]
        for record in records:
            body=json.loads(record[1]);tid=body['threadId']
            if tid in rows:
                pid,_=row_project_identity(rows[tid])
                events.append({**body,'sequence':record[0],'projectId':pid,'title':rows[tid].get('title','')})
        return {'events':events,'nextSequence':records[-1][0] if records else after}

    def projection(self,reader,activity_owner=None,available_only=False,include_unconfirmed=False):
        self.bridge.require()
        with self.lock:
            if self.error:raise ValueError(self.error)
            rows=list(self.rows.values());states=dict(self.states)
            preferences=self.preferences(reader)
            unread_events=self.db.execute('''SELECT e.thread_id,e.kind FROM notification_events e
                LEFT JOIN notification_readers r ON r.thread_id=e.thread_id AND r.reader=?
                LEFT JOIN notification_readers n ON n.thread_id=e.thread_id AND n.reader=?
                WHERE e.sequence>MAX(COALESCE(r.sequence,0),COALESCE(n.sequence,0)) GROUP BY e.thread_id,e.kind''',(reader,self.native_reader())).fetchall()
            unread={row[0] for row in unread_events}
            notified={tid for tid,kind in unread_events if preferences.get(kind,False)}
            sequences={row[0]:row[1] for row in self.db.execute('SELECT thread_id,MAX(sequence) FROM notification_events GROUP BY thread_id')}
            retained={tid for tid,kind in self.db.execute('''SELECT DISTINCT e.thread_id,e.kind FROM notification_events e
                LEFT JOIN activity_cleared c ON c.reader=? AND c.thread_id=e.thread_id
                WHERE e.sequence>COALESCE(c.sequence,0)''',(activity_owner or reader,)) if preferences.get(kind,False)}
        ipc,_=self.bridge.require();groups={};threads=[];project_activity={}
        for row in rows:
            tid=row['id'];native=ipc.current(tid)
            realtime=getattr(self.bridge,'realtime',None)
            status=realtime.thread_status(tid,ipc,native) if realtime else project_status(native)
            available=bool(native and not native.get('_metadataOnly') and status['state'] in ('idle','running','waiting'))
            unconfirmed=native is None and status['state'] in ('unknown','loading')
            if available_only and not available and not (include_unconfirmed and unconfirmed):continue
            # Never preserve cached running/idle after a connection reset or unload.
            known=states.get(tid,{}) if native is not None else {}
            actionable=known.get('actionable',False)
            pid,name=row_project_identity(row)
            thread={**row,'projectId':pid,'projectName':name,'status':status,'available':available,'actionable':actionable,'failed':known.get('failed',False),
                    'unread':tid in unread,'readSequence':sequences.get(tid,0),
                    'activityRetained':tid in retained,'activityRead':tid not in unread,
                    'activityKind':known.get('activityKind','other'),'needsConfirmation':known.get('needsConfirmation',False),
                    'activity':tid in notified or (known.get('failed',False) and preferences['failed'])
                               or (known.get('needsConfirmation',False) and preferences['approval'])}
            from carryon.sessions.timeline import completion_time
            completed=next((value for turn in reversed(turns(native or {})) if (value:=completion_time(turn)) is not None),None)
            if completed is not None:thread['completedAt']=completed
            threads.append(thread)
            group=groups.setdefault(pid,{'id':pid,'name':name,'cwd':'' if row.get('projectless') else row.get('projectRoot',row.get('cwd','')),'total':0,'waiting':0,'running':0,'unread':0,'unknown':0})
            group['rootPaths']=row.get('projectRoots',[]) if not row.get('projectless') else []
            project_activity[pid]=max(project_activity.get(pid,0),row.get('updated_at') or 0)
            group['total']+=1;group['waiting']+=int(actionable);group['running']+=int(status['state']=='running');group['unread']+=int(tid in unread)
            group['unknown']+=int(status['state'] in ('unknown','loading','notLoaded','error'))
        if getattr(self.bridge.catalog, 'independent', False):
            pid, name = project_identity(None)
            groups.setdefault(pid, {'id':pid, 'name':name, 'cwd':'', 'rootPaths':[], 'total':0, 'waiting':0, 'running':0, 'unread':0, 'unknown':0})['canCreate'] = getattr(ipc, 'account_ready', False)
            project_activity.setdefault(pid, 0)
        return sorted(groups.values(),key=lambda g:(-project_activity[g['id']],g['name'],g['id'])),threads

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
                    read=self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM notification_readers WHERE thread_id=? AND reader IN (?, ?)",(tid,reader,self.native_reader())).fetchone()[0]
                    if event['sequence']<=read:continue
                    if kind=='message' and any(preferences[terminal] and self.db.execute(
                        'SELECT 1 FROM notification_events WHERE event_id=?',(digest([tid,event['turnId'],terminal]),)).fetchone()
                        for terminal in ('done','failed')):continue
                    eligible.append(event)
                return {'events':eligible,'nextSequence':packet['nextSequence'],'badge':len(visible)}
        raise ValueError('通知状态正在变化，请稍后重试')

    def dispatch(self,reader,method,path,data,query,activity_owner=None):
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
        if path=='/api/notifications/clear-read' and method=='POST':return 200,self.clear_read(reader,activity_owner)
        limit=min(100,max(1,int(query.get('limit',['100'])[0])));offset=max(0,int(query.get('offset',['0'])[0]))
        if path=='/api/notifications' and method=='GET':return 200,self.events(reader,max(0,int(query.get('after',['0'])[0])),limit)
        if method!='GET':return 404,{'error':'接口不存在'}
        if query.get('sync',[''])[0]=='full' or query.get('syncId'):
            progress=self.sync.poll(query['syncId'][0]) if query.get('syncId') else self.sync.start()
            if progress['state']!='completed':return 200,{'sync':progress}
            query={key:value for key,value in query.items() if key not in ('sync','syncId','refreshStatuses')}
            status,result=self.dispatch(reader,method,path,data,query,activity_owner)
            return status,{**result,'sync':progress}
        realtime=getattr(self.bridge,'realtime',None)
        status_list=path in ('/api/projects','/api/workspace/threads') or path.startswith('/api/projects/') and path.endswith('/threads')
        refresh=query.get('refreshStatuses',['false'])[0]=='true'
        if refresh and (status_list or path=='/api/activity'):
            self.catalog_refresh()
            if realtime:realtime.sync_watches()
            self.bridge.notify()
        if realtime and status_list and refresh:
            # Select from the unfiltered directory so an earlier routing miss can
            # be rechecked even when its row is currently hidden.
            with self.lock:rows=list(self.rows.values())
            search=query.get('search',[''])[0].casefold()
            if path.startswith('/api/projects/') and path.endswith('/threads'):
                rows=[row for row in rows if row_project_identity(row)[0]==path.split('/')[3]]
            if path=='/api/projects':
                rows=[row for row in rows if search in (' '.join([row_project_identity(row)[1],row.get('cwd',''),*row.get('projectRoots',[])])).casefold()]
            else:
                rows=[row for row in rows if search in (row.get('title','')+' '+row.get('cwd','')).casefold()]
            if path=='/api/workspace/threads' and query.get('threadId'):
                rows=[row for row in rows if row['id']==query['threadId'][0]]
            rows.sort(key=lambda row:(row.get('updated_at') or 0,row['id']),reverse=True)
            realtime.refresh_statuses([row['id'] for row in rows[offset:offset+limit]])
        available_only=query.get('availableOnly',['false'])[0]=='true'
        groups,threads=self.projection(reader,activity_owner,available_only=True,include_unconfirmed=path!='/api/activity') if available_only else (self.projection(reader,activity_owner) if activity_owner is not None else self.projection(reader))
        search=query.get('search',[''])[0].casefold()
        if path=='/api/projects':
            groups=[g for g in groups if search in (' '.join([g['name'],g['cwd'],*g['rootPaths']])).casefold()]
            return 200,{'projects':groups[offset:offset+limit],'total':len(groups),'nextOffset':offset+limit}
        if path=='/api/activity':
            include_read=query.get('includeRead',['false'])[0]=='true'
            if include_read:
                threads=[t for t in threads if t['activityRetained'] or (t['activity'] and t['readSequence']==0)]
            else:threads=[t for t in threads if t['activity']]
            # An earlier notification must not turn the activity page into a live task list.
            # Keep the notification stored; it becomes visible again once execution settles.
            threads=[t for t in threads if t['status']['state']!='running' or t.get('needsConfirmation',False)]
            threads=[t for t in threads if t['id']!=query.get('excludeThreadId',[''])[0]]
        elif path.startswith('/api/projects/') and path.endswith('/threads'):
            pid=path.split('/')[3];threads=[t for t in threads if t['projectId']==pid]
        elif path!='/api/workspace/threads':return 404,{'error':'接口不存在'}
        threads=[t for t in threads if search in (t.get('title','')+' '+t.get('cwd','')).casefold()]
        if path=='/api/workspace/threads' and query.get('threadId'):
            threads=[t for t in threads if t['id']==query['threadId'][0]]
        mode=query.get('filter',['all'])[0]
        if mode not in ('all','waiting','running','unread'):raise ValueError('无效筛选')
        if mode=='waiting':threads=[t for t in threads if t['actionable']]
        if mode=='running':threads=[t for t in threads if t['status']['state']=='running']
        if mode=='unread':threads=[t for t in threads if t['unread']]
        threads.sort(key=lambda t: (t.get('updated_at') or 0, t['id']), reverse=True)
        if path=='/api/activity':threads.sort(key=lambda t: not t['actionable'])
        result={'threads':threads[offset:offset+limit],'total':len(threads),'nextOffset':offset+limit}
        if path=='/api/activity':
            preferences=self.preferences(reader)
            ipc,_=self.bridge.require()
            native_states={thread['id']:ipc.current(thread['id']) for thread in result['threads']}
            with self.lock:
                for thread in result['threads']:
                    native=native_states[thread['id']]
                    known=self.states.get(thread['id'],{}) if native and not native.get('_metadataOnly') else {}
                    value=known.get('activityPreview')
                    if value is None:
                        kinds=[kind for kind,enabled in preferences.items() if enabled]
                        if kinds:
                            event=self.db.execute('SELECT body FROM notification_events WHERE thread_id=? AND kind IN ('+
                                                  ','.join('?' for _ in kinds)+') ORDER BY sequence DESC LIMIT 1',
                                                  (thread['id'],*kinds)).fetchone()
                            if event:value=json.loads(event[0]).get('preview')
                    if value is not None:thread['activityPreview']=value
            current=query.get('currentThreadId',[''])[0]
            result['currentThreadIncluded']=any(t['id']==current for t in threads)
        return 200,result
