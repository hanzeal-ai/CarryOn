"""Durable per-installation notification cursors, independent of app WebSockets."""
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from .apns import APNsError

LABELS={'done':'任务已完成','failed':'任务执行失败','approval':'任务需要你确认','message':'收到新消息'}


class PushService:
    def __init__(self,server,path,sender):
        self.server=server;self.sender=sender;self.lock=threading.RLock();self.stop=threading.Event()
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,check_same_thread=False);os.chmod(path,0o600)
        self.db.row_factory=sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS installations(
            id TEXT PRIMARY KEY, token TEXT NOT NULL, environment TEXT NOT NULL, device TEXT NOT NULL,
            session TEXT NOT NULL, generation TEXT NOT NULL, cursor INTEGER, badge INTEGER,
            updated REAL NOT NULL, retry_at REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
            error TEXT)''');self.db.commit()
        with self.lock:
            if 'revision' not in {r[1] for r in self.db.execute('PRAGMA table_info(installations)')}:
                self.db.execute('ALTER TABLE installations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
            if 'authority' not in {r[1] for r in self.db.execute('PRAGMA table_info(installations)')}:
                self.db.execute("ALTER TABLE installations ADD COLUMN authority TEXT NOT NULL DEFAULT ''")
            self.db.execute('CREATE TABLE IF NOT EXISTS registration_versions(authority TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(authority,id))')
            if 'authority' not in {r[1] for r in self.db.execute('PRAGMA table_info(registration_versions)')}:
                self.db.execute('BEGIN')
                self.db.execute('ALTER TABLE registration_versions RENAME TO registration_versions_legacy')
                self.db.execute('CREATE TABLE registration_versions(authority TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(authority,id))')
                self.db.execute("INSERT INTO registration_versions SELECT '',id,revision FROM registration_versions_legacy")
                self.db.execute('DROP TABLE registration_versions_legacy')
            self.db.commit()
        self.worker=threading.Thread(target=self.run,daemon=True,name='apns-notifications');self.worker.start()

    def register(self,data,session):
        ident=data.get('installationId');token=data.get('token');environment=data.get('environment');device=data.get('deviceId')
        if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f-]{36}',ident):raise ValueError('安装编号无效')
        if not isinstance(token,str) or not re.fullmatch(r'[0-9a-f]{32,512}',token) or len(token)%2:raise ValueError('推送 Token 无效')
        if environment not in ('sandbox','production'):raise ValueError('推送环境无效')
        revision=data.get('revision')
        if hasattr(self.server.auth, 'identity'):
            from .workspace_access import require
            with self.server.auth_lock, self.server.lock:
                require(self.server, session, device)
        if type(revision) is not int or not 1<=revision<=9007199254740991:raise ValueError('注册版本无效')
        with self.server.auth_lock,self.server.lock,self.lock:
            if self.server.sessions.get(session,0)<=time.monotonic():raise PermissionError('登录已过期，请重新登录')
            if not isinstance(device,str) or device not in self.server.config['devices']:raise PermissionError('设备未授权')
            if hasattr(self.server.auth, 'identity'):
                previous_owner = self.db.execute('SELECT session FROM installations WHERE id=? OR (token=? AND environment=?)',(ident,token,environment)).fetchall()
                if any(self.server.auth.identity(row['session']) != self.server.auth.identity(session) for row in previous_owner):
                    raise PermissionError('通知安装不属于当前账号')
            known=self.db.execute('SELECT revision FROM registration_versions WHERE authority=? AND id=?',(self.server.auth.fingerprint,ident)).fetchone()
            if known and revision<=known[0]:return {'registered':False,'superseded':True}
            self.db.execute('INSERT OR REPLACE INTO registration_versions VALUES(?,?,?)',(self.server.auth.fingerprint,ident,revision));self.db.commit()
            previous=self.db.execute('SELECT device,authority FROM installations WHERE id=?',(ident,)).fetchone()
            needs_baseline=previous is None or previous['device']!=device or previous['authority']!=self.server.auth.fingerprint
            connection=self.server.devices.get(device)
        baseline=None
        if needs_baseline and connection is not None and not connection.closed:
            response=connection.call({'type':'request','method':'GET','path':'/api/notifications/push','body':None},timeout=5)
            if response['status']!=200:raise ConnectionError('本机通知服务暂不可用，请稍后重试注册')
            baseline=response['body'].get('nextSequence')
            if type(baseline) is not int or baseline<0:raise ValueError('通知游标无效')
        with self.server.auth_lock,self.server.lock,self.lock:
            if self.server.sessions.get(session,0)<=time.monotonic():raise PermissionError('登录已过期，请重新登录')
            if device not in self.server.config['devices']:raise PermissionError('设备已撤销')
            if self.db.execute('SELECT revision FROM registration_versions WHERE authority=? AND id=?',(self.server.auth.fingerprint,ident)).fetchone()[0]!=revision:
                return {'registered':False,'superseded':True}
            previous=self.db.execute('SELECT * FROM installations WHERE id=?',(ident,)).fetchone()
            if (previous is None or previous['authority']!=self.server.auth.fingerprint) and self.db.execute('SELECT COUNT(*) FROM installations WHERE authority=?',(self.server.auth.fingerprint,)).fetchone()[0]>=256:raise ValueError('推送设备数量已达上限')
            same_scope=previous is not None and previous['device']==device and previous['authority']==self.server.auth.fingerprint
            if same_scope:
                # Token rotation must not discard pending events or retry state.
                self.db.execute('DELETE FROM installations WHERE token=? AND environment=? AND id!=?',(token,environment,ident))
                self.db.execute('UPDATE installations SET token=?,environment=?,session=?,generation=?,updated=?,revision=? WHERE id=?',
                                (token,environment,session,uuid.uuid4().hex,time.time(),revision,ident))
            else:
                self.db.execute('DELETE FROM installations WHERE token=? AND environment=?',(token,environment))
                self.db.execute('INSERT OR REPLACE INTO installations(id,token,environment,device,session,generation,updated,cursor,revision,authority) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (ident,token,environment,device,session,uuid.uuid4().hex,time.time(),baseline,revision,self.server.auth.fingerprint))
            self.db.commit()
        return {'registered':True}

    def unregister_session(self,session):
        with self.lock:
            self.db.execute('DELETE FROM installations WHERE session=?',(session,));self.db.commit()

    def unregister(self,ident,session,revision):
        if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f-]{36}',ident):raise ValueError('安装编号无效')
        if type(revision) is not int or not 1<=revision<=9007199254740991:raise ValueError('注册版本无效')
        with self.server.auth_lock,self.lock:
            if self.server.sessions.get(session,0)<=time.monotonic():raise PermissionError('登录已过期，请重新登录')
            if hasattr(self.server.auth, 'identity'):
                previous = self.db.execute('SELECT session FROM installations WHERE id=?',(ident,)).fetchone()
                if previous and self.server.auth.identity(previous['session']) != self.server.auth.identity(session):
                    raise PermissionError('通知安装不属于当前账号')
            known=self.db.execute('SELECT revision FROM registration_versions WHERE authority=? AND id=?',(self.server.auth.fingerprint,ident)).fetchone()
            if known and revision<=known[0]:return
            self.db.execute('INSERT OR REPLACE INTO registration_versions VALUES(?,?,?)',(self.server.auth.fingerprint,ident,revision))
            # Console sessions share one owner; permission denial revokes this installation across logins.
            self.db.execute('DELETE FROM installations WHERE id=?',(ident,));self.db.commit()

    def revoke(self,device):
        with self.lock:
            self.db.execute('DELETE FROM installations WHERE device=?',(device,));self.db.commit()

    def current(self,row):
        if hasattr(self.server.auth, 'identity'):
            from .workspace_access import require
            try:
                with self.server.auth_lock, self.server.lock:
                    require(self.server, row['session'], row['device'])
            except PermissionError:
                return False
        with self.lock:
            return self.db.execute('SELECT 1 FROM installations WHERE id=? AND generation=? AND authority=?',(row['id'],row['generation'],self.server.auth.fingerprint)).fetchone() is not None

    def update(self,row,**values):
        with self.lock:
            self.db.execute('UPDATE installations SET '+','.join(k+'=?' for k in values)+' WHERE id=? AND generation=?',
                            (*values.values(),row['id'],row['generation']));self.db.commit()

    def deliver(self,row):
        if not self.current(row):return
        with self.server.lock:device=self.server.devices.get(row['device'])
        if device is None or device.closed:return
        after='' if row['cursor'] is None else '?after='+str(row['cursor'])
        response=device.call({'type':'request','method':'GET','path':'/api/notifications/push'+after,'body':None},timeout=5)
        if response['status']!=200:raise ValueError('本机通知快照暂不可用')
        packet=response['body'];badge=packet['badge'];cursor=packet['nextSequence']
        if type(badge) is not int or badge<0 or type(cursor) is not int or cursor<0:raise ValueError('通知快照格式无效')
        if row['cursor'] is not None and cursor<row['cursor']:raise ValueError('本机通知游标倒退，需核对原数据目录')
        links=getattr(self.server,'links',None)
        if links is not None and (not hasattr(self.server.auth, 'identity') or self.server.auth.identity(row['session']) == 'owner'):
            badge+=len(links.pending())
        for event in packet['events']:
            if self.stop.is_set() or not self.current(row):return
            payload={'aps':{'alert':{'title':LABELS[event['kind']],'body':event['title'][:120]},
                            'badge':badge,'sound':'default','thread-id':row['device']+':'+event['threadId']},
                     'server':self.server.public_url,'deviceId':row['device'],'threadId':event['threadId'],'eventId':event['eventId']}
            self.sender.send(row['token'],row['environment'],payload,row['id']+event['eventId'])
            self.update(row,cursor=event['sequence'],badge=badge)
        if not packet['events'] and row['badge']!=badge and not self.stop.is_set() and self.current(row):
            self.sender.send(row['token'],row['environment'],{'aps':{'badge':badge},'deviceId':row['device']},
                             row['id']+f':badge:{cursor}:{badge}')
        self.update(row,cursor=cursor,badge=badge,failures=0,error=None,retry_at=0)

    def tick(self):
        with self.lock:
            self.db.execute('DELETE FROM installations WHERE updated<?',(time.time()-90*86400,));self.db.commit()
            rows=self.db.execute('SELECT * FROM installations WHERE retry_at<=? AND authority=?',(time.time(),self.server.auth.fingerprint)).fetchall()
        for row in rows:
            if self.stop.is_set():return
            try:self.deliver(row)
            except APNsError as exc:
                if exc.status==410 or exc.reason in ('BadDeviceToken','DeviceTokenNotForTopic'):
                    with self.lock:
                        self.db.execute('DELETE FROM installations WHERE id=? AND generation=?',(row['id'],row['generation']));self.db.commit()
                else:self.retry(row,str(exc))
            except Exception as exc:self.retry(row,type(exc).__name__)

    def retry(self,row,error):
        failures=row['failures']+1
        self.update(row,failures=failures,error=error,retry_at=time.time()+min(3600,5*2**min(failures,10)))

    def run(self):
        while not self.stop.wait(5):self.tick()

    def close(self):
        self.stop.set();self.worker.join(20)
        # Do not close a connection while its bounded network call is unwinding.
        if not self.worker.is_alive():
            self.sender.close()
            with self.lock:self.db.close()
