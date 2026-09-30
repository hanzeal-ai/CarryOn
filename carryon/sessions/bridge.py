import hashlib
import json
import threading
import time
import uuid

from carryon.errors import BridgeError
from carryon.sessions.catalog import valid_id
from carryon.desktop_ipc.ipc import DesktopIPC, IPCError
from carryon.sessions.timeline import project_timeline
from carryon.sessions.thread_status import project_status, idle_snapshot
from concurrent.futures import ThreadPoolExecutor


def snapshot_history(state, turn_cache=None, limit=None):
    """Render app-server/rollout turns and the desktop's canonical paginated history."""
    from carryon.sessions.operations import turns as native_turns
    canonical = state.get("turnHistory", {})
    complete = canonical.get("history", {}).get("isComplete", False) if canonical.get("kind") == "canonical" else True
    turns = native_turns(state)
    total = len(turns)
    offset = max(0, total - limit) if limit else 0
    earlier_duration = sum(t.get("durationMs", 0) for t in turns[:offset] if isinstance(t.get("durationMs", 0), (int, float)))
    turns = turns[offset:]
    return {**project_timeline(turns, state, turn_cache, offset),
            "executionBackend": state.get("executionBackend", "desktop"),
            **({"historyWindow": {"limit": limit, "total": total, "hasMore": offset > 0}, "earlierDurationMs": earlier_duration} if limit else {}),
            "status": project_status(state),
            "thread": {"id": state["id"], "title": state.get("title", ""), "cwd": state.get("cwd", "")},
            "truncated": not complete,
            "source": "desktop-snapshot"}


class Bridge:
    @property
    def subagents(self):
        from carryon.sessions.subagents import Subagents
        return Subagents(self)

    def subagent_history(self, thread_id, limit=None):
        row = self.catalog.get(thread_id)
        ipc, generation = self.require()
        state = ipc.current(thread_id) if hasattr(ipc, 'current') else None
        persisted = state is None
        if persisted:
            state = self.catalog.rollout_state(thread_id, limit=limit)
        result = self.history_cache.project(state, snapshot_history, limit=limit, segmented=True)
        if persisted:
            result.update(source='local-rollout', controls={}, pendingRequests=[])
            if state.get('rolloutWindow'):
                result.update(historyWindow=state['rolloutWindow'], earlierDurationMs=state['earlierDurationMs'])
        else:
            try: result['queue'] = self.queue(thread_id)
            except (ValueError, OSError): pass
        result = self.subagents.resolve_titles(self.subagents.decorate(result, row))
        result['historyRevision'] += ':' + hashlib.sha256(json.dumps([result['access'], result.get('queue')], sort_keys=True).encode()).hexdigest()
        with self.lock:
            self.check_generation(ipc, generation)
        return result

    def __init__(self, socket_path, catalog, journal, ipc_factory=DesktopIPC):
        self.socket_path = socket_path
        self.catalog = catalog
        self.journal = journal
        self.ipc_factory = ipc_factory
        self.ipc = None
        self.enabled = False
        self.generation = 0
        self.workspace_session = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.events = threading.Condition()
        self.event_revision = 0
        self.side_registry = {}
        self.side_scanning = False
        self.side_scanned_at = 0
        self.side_error = None
        self.refreshing_jobs = set()
        self.realtime = None
        self.journal.on_change = self.notify
        from carryon.sessions.history_cache import HistoryCache
        self.history_cache = HistoryCache()

    def open_stream(self):
        from carryon.routes.realtime import Realtime
        with self.lock:
            if self.realtime is None or self.realtime.closed.is_set():
                self.realtime = Realtime(self)
            return self.realtime.open()

    def notify(self):
        with self.events:
            self.event_revision += 1
            self.events.notify_all()

    def native_read(self, ipc, tid, state=None, token=None):
        with self.lock:
            if not self.enabled or self.ipc is not ipc or not ipc.connected:
                return
            workspace = getattr(self, 'workspace', None)
            if workspace is None or tid not in workspace.thread_ids():
                return
            # Same lock order as dispatch: bridge, then IPC. No later snapshot or
            # read invalidation can overtake validation and cursor advancement.
            with ipc.lock:
                if (token is None or state is None or ipc.current(tid) is not state
                        or state.get('hasUnreadTurn') is not False
                        or ipc.events.read_refreshes.get(tid) is not token
                        or tid in ipc.events.read_dirty):
                    return
                workspace.observe(state)
                workspace.read('native:codex', tid, workspace.latest_sequence(tid))

    def status(self):
        import socket
        with self.lock:
            return {"enabled": self.enabled and bool(self.ipc and self.ipc.connected),
                    "workspaceSession": self.workspace_session,
                    "protocol": getattr(self.ipc_factory, 'protocol', 'codex-desktop-ipc'),
                    "testedDesktopVersion": "26.901.51231",
                    **({'accountReady': self.ipc.account_ready} if self.ipc is not None and hasattr(self.ipc, 'account_ready') else {}),
                    "deviceInfo": {"hostname": socket.gethostname(), **getattr(self, "listener_info", {})}}

    def enable(self):
        with self.lock:
            if self.enabled and self.ipc and self.ipc.connected:
                return self.status()
            ipc = self.ipc_factory(self.socket_path)
            try:
                ipc.connect()
            except (OSError, IPCError, ValueError) as exc:
                label = '无法启动工作区 app-server：' if getattr(self.ipc_factory, 'protocol', None) else '无法连接 Codex App，请确认应用已启动：'
                raise BridgeError(label + str(exc), 503) from exc
            ipc.on_change = self.notify
            ipc.on_read = lambda tid, state=None, token=None: self.native_read(ipc, tid, state, token)
            self.ipc = ipc
            self.enabled = True
            self.generation += 1
            self.side_registry = {}
            self.side_scanned_at = 0
            self.notify()
            return self.status()

    def disable(self):
        with self.lock:
            self.enabled = False
            self.history_cache.clear()
            self.generation += 1
            ipc, self.ipc = self.ipc, None
            if self.realtime is not None:
                self.realtime.sync_watches()
        self.notify()
        if ipc:
            ipc.close()
        return self.status()

    def require(self):
        with self.lock:
            if not self.enabled or not self.ipc or not self.ipc.connected:
                raise BridgeError("桥接未开启或连接已断开", 403)
            return self.ipc, self.generation

    def side_chats(self, parent_id):
        self.catalog.get(parent_id)
        ipc, generation = self.require()
        with self.lock:
            if not self.side_scanning and time.monotonic() - self.side_scanned_at > 30:
                self.side_scanning = True
                threading.Thread(target=self._discover_sides, args=(ipc, generation), daemon=True).start()
            chats = [{**meta, **project_status(ipc.current(tid))}
                     for tid, meta in self.side_registry.items() if meta['parentId'] == parent_id]
            return {'chats':chats, 'scanning':self.side_scanning, 'error':self.side_error,
                    'scope':'registered-live-side-chats'}

    def _discover_sides(self, ipc, generation):
        def discover(tid):
            try:
                with self.lock:
                    self.check_generation(ipc, generation)
                state = ipc.current(tid)
                if state is None:
                    _, state = ipc.sidebar_snapshot(tid)
                parent = state.get('forkedFromId')
                if state.get('sideConversation') is not True or state.get('ephemeral') is not True or not parent:
                    return
                valid_id(parent)
                with self.lock:
                    self.check_generation(ipc, generation)
                    self.side_registry[tid] = {'id':tid, 'parentId':parent,
                        'title':state.get('title') or '临时聊天'}
                self.notify()
            except (ValueError, IPCError, OSError, BridgeError):
                pass  # A persisted binding is not proof of a still-live side chat.
        try:
            candidates = self.catalog.side_candidates()
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix='side-discovery') as pool:
                list(pool.map(discover, candidates))
            self.side_error = None
        except (ValueError, OSError) as exc:
            self.side_error = '暂时无法读取临时聊天的发现记录'
        finally:
            with self.lock:
                self.side_scanning = False
                self.side_scanned_at = time.monotonic() if self.generation == generation else 0
            self.notify()

    def side_state(self, parent_id, side_id, state=None):
        valid_id(side_id)
        self.catalog.get(parent_id)
        ipc, generation = self.require()
        with self.lock:
            if self.side_registry.get(side_id, {}).get('parentId') != parent_id:
                raise ValueError('尚未核验此临时聊天属于当前会话')
        state = state if state is not None else ipc.current(side_id)
        if state is None:
            _, state = ipc.sidebar_snapshot(side_id)
        if (state.get('id') != side_id or state.get('sideConversation') is not True or state.get('ephemeral') is not True
                or state.get('forkedFromId') != parent_id):
            raise ValueError('临时聊天关联已失效')
        with self.lock:
            self.check_generation(ipc, generation)
        return state

    def assert_target(self, thread_id, parent_id=None, state=None):
        if parent_id is not None:
            self.side_state(parent_id, thread_id, state)
        else:
            self.subagents.assert_interactive(thread_id)

    def side_history(self, parent_id, side_id, limit=None):
        state = self.side_state(parent_id, side_id)
        result = self.history_cache.project(state, snapshot_history, segmented=True, limit=limit)
        result['parentId'] = parent_id
        result['access'] = {'canInteract': True, 'nativeReady': True}
        try: result['queue'] = self.queue(side_id, parent_id)
        except (ValueError, OSError): result['queue'] = {'error': '无法读取原生排队消息，请稍后刷新'}
        return result

    def image(self, thread_id, identifier, parent_id=None):
        from carryon.sessions.images import read_history_image
        ipc, generation = self.require()
        history = self.side_history(parent_id, thread_id) if parent_id is not None else self.history(thread_id)
        result = read_history_image(history, identifier)
        with self.lock:
            self.check_generation(ipc, generation)
        return result

    def artifact(self, thread_id, identifier, parent_id=None):
        from carryon.sessions.artifacts import read_artifact
        ipc, generation = self.require()
        history = self.side_history(parent_id, thread_id) if parent_id is not None else self.history(thread_id)
        result = read_artifact(history, identifier)
        with self.lock:
            self.check_generation(ipc, generation)
        return result

    def persisted_history(self, thread_id, limit=None):
        """Read persisted history without requiring a loaded native conversation."""
        ipc, generation = self.require()
        row = self.catalog.get(thread_id)
        from carryon.sessions.subagents import is_subagent
        if is_subagent(row):
            return self.subagent_history(thread_id, limit)
        state = self.catalog.rollout_state(thread_id, limit=limit)
        result = self.history_cache.project(state, snapshot_history, limit=limit, segmented=True)
        if state.get('rolloutWindow'):
            result.update(historyWindow=state['rolloutWindow'], earlierDurationMs=state['earlierDurationMs'])
        status = {'state': 'unknown', 'label': '状态未知'}
        with self.lock:
            previous = self.realtime.unavailable.get(thread_id) if self.realtime else None
            if previous and previous[0] is ipc and previous[2]:
                status = dict(previous[2])
            self.check_generation(ipc, generation)
        status['label'] = '历史已同步 · ' + status['label']
        result.update(source='local-rollout', syncing=False, controls={}, pendingRequests=[],
                      runtime={'type': status['state']}, status=status)
        result = self.subagents.resolve_titles(self.subagents.decorate(result, row))
        result['historyRevision'] = 'persisted:' + result['historyRevision'] + ':' + status['state']
        with self.lock:
            self.check_generation(ipc, generation)
        return result

    def history(self, thread_id, limit=None):
        row = self.catalog.get(thread_id)
        from carryon.sessions.subagents import is_subagent
        if is_subagent(row):
            return self.subagent_history(thread_id, limit)
        ipc, generation = self.require()
        state = ipc.current(thread_id) if hasattr(ipc, 'current') else None
        if state is None or state.get('_metadataOnly'):
            return self.persisted_history(thread_id, limit)
        result = self.history_cache.project(state, snapshot_history, limit=limit, segmented=True)
        try:
            result['queue'] = self.queue(thread_id)
            result['historyRevision'] += ':' + result['queue']['fingerprint']
        except (ValueError, OSError):
            result['queue'] = {'error': '无法读取原生排队消息，请稍后刷新'}
            result['historyRevision'] += ':queue-unavailable'
        result = self.subagents.resolve_titles(result)
        with self.lock:
            self.check_generation(ipc, generation)
        return result

    def queue(self, thread_id, parent_id=None, *, authoritative=False):
        from carryon.sessions.queue import projection
        if parent_id is not None: self.side_state(parent_id, thread_id)
        else: self.catalog.get(thread_id)
        ipc, generation = self.require()
        cached = None
        if not authoritative and hasattr(ipc, 'events'):
            with ipc.lock:
                cached = ipc.events.queues.get(thread_id)
        if cached is None:
            result = projection(self.catalog.queued(thread_id), 'desktop-persisted')
        else:
            result = projection(cached, 'desktop-broadcast')
        with self.lock:
            self.check_generation(ipc, generation)
        return result

    def check_generation(self, ipc, generation):
        if not self.enabled or self.ipc is not ipc or self.generation != generation:
            raise BridgeError("桥接已取消，此请求未获准继续", 403)

    def send_snapshot(self, ipc, generation, thread_id, authorize=None, parent_id=None):
        return ipc.snapshot(thread_id)

    def compose(self,thread_id,request_id,prompt,images=None,source=None,authorize=None,parent_id=None):
        from carryon.contracts import digest, text, validate_request_id
        from carryon.sessions.operations import controls, submit as operate
        from carryon.sessions.images import validate_images
        # Idempotency binds the original wire payload, before native text normalization.
        raw_prompt = prompt
        images=validate_images(images)
        prompt=text(prompt, allow_empty=bool(images))
        validate_request_id(request_id)
        valid_id(thread_id)
        self.assert_target(thread_id, parent_id)
        fingerprint=digest([thread_id,raw_prompt,images] + ([parent_id] if parent_id else []))
        ipc,generation=self.require()
        previous=self.journal.get(request_id)
        if previous:
            if previous.get('composeFingerprint')!=fingerprint:raise BridgeError('requestId 已用于不同内容')
            return previous
        owner,state=self.send_snapshot(ipc,generation,thread_id,authorize,parent_id)
        with self.lock:
            self.check_generation(ipc,generation)
            if authorize:authorize()
            self.assert_target(thread_id, parent_id, state)
            status=project_status(state)['state'];metadata={**(source or {}),'composeFingerprint':fingerprint}
        # Never hold the bridge gate while waiting for a native response: stream
        # updates, cancellation and approval replies must remain able to proceed.
        if status=='idle':return self.submit('message',request_id,prompt,thread_id,images,metadata,authorize,parent_id=parent_id)
        if status not in ('running','waiting'):raise BridgeError('会话状态尚未确认，不能投递或排队')
        data={'requestId':request_id,'prompt':prompt}
        if images:data['images']=images
        if status=='waiting':
            data.update(action='queue-add',queueFingerprint=self.queue(thread_id, parent_id, authoritative=True)['fingerprint'])
        else:
            data.update(action='steer',expectedTurnId=controls(state)['activeTurnId'])
        return operate(self,thread_id,data,metadata,authorize,prepared=(owner,state),parent_id=parent_id)

    def submit(self, kind, request_id, prompt, thread_id=None, images=None, source=None, authorize=None, parent_id=None):
        if kind != "message": raise ValueError("新建会话请通过项目创建接口提交")
        from carryon.sessions.images import validate_images
        images=validate_images(images)
        from carryon.contracts import text, validate_request_id
        validate_request_id(request_id)
        prompt = text(prompt, allow_empty=bool(images))
        ipc, generation = self.require()
        with self.lock:
            if not thread_id:
                raise BridgeError("请指定目标会话")
            valid_id(thread_id)
            fingerprint = hashlib.sha256(json.dumps([kind, thread_id, prompt]+([images] if images else [])+([parent_id] if parent_id else []), ensure_ascii=False).encode()).hexdigest()
            previous = self.journal.get(request_id)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise BridgeError("requestId 已用于不同内容")
                return previous
            # Protect concurrent turn-start writes, never the lifetime of a task.
            if any(j['threadId'] == thread_id and j['state'] in ('preparing', 'dispatching')
                   and j['kind'] in ('message', 'create', 'operation:edit', 'operation:resume', 'operation:compact')
                   for j in self.journal.list()):
                raise BridgeError('会话正在提交操作，请稍后重试')
            self.assert_target(thread_id, parent_id)
            job = {"id": request_id, "kind": kind, "threadId": thread_id,
                   "state": "preparing", "created": time.time(), "fingerprint": fingerprint,
                   "clientMessageId": str(uuid.uuid4())}
            if source:job.update(source)
            if parent_id is not None: job['sideParentId'] = parent_id
            self.journal.insert(job)
        self._dispatch(job, prompt, ipc, generation, images, authorize)
        return self.journal.get(request_id)

    def _dispatch(self, job, prompt, ipc, generation, images=None, authorize=None):
        dispatched = False
        try:
            owner, state = self.send_snapshot(ipc, generation, job["threadId"], authorize, job.get('sideParentId'))
            self.assert_target(job['threadId'], job.get('sideParentId'), state)
            idle_snapshot(state)

            def guarded_send(write):
                nonlocal dispatched
                with self.lock:
                    self.check_generation(ipc, generation)
                    if authorize:authorize()
                    self.assert_target(job['threadId'], job.get('sideParentId'))
                    current = ipc.current(job['threadId']) if hasattr(ipc, 'current') else None
                    if current is not None: idle_snapshot(current)
                    self.journal.update(job["id"], state="dispatching")
                    dispatched = True
                    write()

            turn = ipc.start(job["threadId"], prompt, owner, job["clientMessageId"], guarded_send, **({"images":images} if images else {}))
            self.journal.update(job["id"], state="accepted", turnId=turn["id"], evidence="native-handler-response")
        except Exception as exc:
            uncertain = dispatched and not (isinstance(exc, IPCError) and not exc.uncertain)
            self.journal.update(job["id"], state="uncertain" if uncertain else "failed", error=str(exc))

    def refresh_job(self, job_id):
        self.require()
        with self.lock:
            if job_id in self.refreshing_jobs:
                return self.journal.get(job_id)
            self.refreshing_jobs.add(job_id)
        try:
            return self._refresh_job(job_id)
        finally:
            with self.lock:
                self.refreshing_jobs.discard(job_id)

    def turn_evidence(self, thread_id, turn_id, parent_id=None):
        """Read only the requested native turn; job tracking needs no display timeline."""
        from carryon.sessions.operations import turns
        if parent_id is not None: self.side_state(parent_id, thread_id)
        else: self.catalog.get(thread_id)
        ipc, generation = self.require()
        try:
            state = ipc.current(thread_id) if hasattr(ipc, 'current') else None
            if state is None:
                _, state = ipc.snapshot(thread_id)
            native = next((turn for turn in reversed(turns(state)) if turn.get('turnId') == turn_id), None)
        except IPCError as exc:
            if str(exc) != 'no-client-found': raise
            persisted = self.catalog.rollout_index(thread_id).snapshot(turn_id=turn_id)
            native = next(iter(persisted['turns']), None)
        evidence = None if native is None else {'status': native.get('status', 'unknown')}
        with self.lock:
            self.check_generation(ipc, generation)
        return evidence

    def _recover_receipt(self, job):
        """Recover a lost acknowledgement only from the exact native message ID."""
        from carryon.sessions.operations import turns
        ipc, generation = self.require()
        try:
            self.assert_target(job['threadId'], job.get('sideParentId'))
            _, state = ipc.snapshot(job['threadId'])
            identifier = job['clientMessageId']
            for turn in turns(state):
                for item in turn.get('items', []):
                    if item.get('type') not in ('userMessage', 'steeringUserMessage'):
                        continue
                    if identifier not in (item.get('id'), item.get('clientUserMessageId'), item.get('clientMessageId'), item.get('clientId')):
                        continue
                    rejected = item.get('status') == 'rejected'
                    with self.lock:
                        self.check_generation(ipc, generation)
                        return self.journal.update(job['id'], expected=job,
                            state='failed' if rejected else ('accepted' if job['kind'] == 'message' else 'completed'),
                            turnId=turn.get('turnId'), error='原生端拒绝了此消息' if rejected else None,
                            evidence='native-message-id')
            if job['kind'] == 'operation:queue-add':
                queue = self.queue(job['threadId'], job.get('sideParentId'))
                if any(item.get('id') == identifier for item in queue['messages']):
                    with self.lock:
                        self.check_generation(ipc, generation)
                        return self.journal.update(job['id'], expected=job, state='completed', error=None,
                                                   evidence='native-queue-id')
        except (ValueError, IPCError, BridgeError):
            pass
        return self.journal.get(job['id'])

    def _refresh_job(self, job_id):
        job = self.journal.get(job_id)
        if job is None:
            raise BridgeError("请求不存在", 404)
        if job["state"] == "uncertain" and job.get("clientMessageId"):
            job = self._recover_receipt(job)
        return job

    def resolve(self, job_id):
        """Explicit acknowledgement only; it never resends an uncertain request."""
        self.require()
        with self.lock:
            job = self.journal.get(job_id)
            if job and job['kind'] == 'quota-reset':
                raise BridgeError('重置卡必须用原请求核对原生回执，不能手动清除未知结果', 409)
            if not job or job["state"] != "uncertain":
                raise BridgeError("只有结果待确认的请求需要人工核对")
            return self.journal.update(job_id, expected=job, state="acknowledged",
                error="用户已在 Codex App 核对；此操作不重发请求")
