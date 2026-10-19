"""Native goal state and user-authorized mutations; no local continuation loop."""
from contextlib import nullcontext
from carryon.errors import IPCError
from carryon.sessions.history_cache import NativeSnapshot

STATUSES = {'active', 'paused', 'blocked', 'usageLimited', 'budgetLimited', 'complete'}


def value(result, tid):
    if not isinstance(result, dict) or 'goal' not in result: raise IPCError('原生目标回执缺少goal')
    goal = result['goal']
    if goal is not None and (not isinstance(goal, dict) or goal.get('threadId') != tid
            or goal.get('status') not in STATUSES or not isinstance(goal.get('objective'), str)):
        raise IPCError('原生目标身份或状态无效')
    return goal


def loaded(runtime, tid):
    state = runtime.current(tid)
    if not state or state.get('_metadataOnly') or not runtime.connected:
        raise IPCError('目标操作需要已加载的原生会话')
    return state


def read(runtime, tid):
    with runtime.lock:
        state = loaded(runtime, tid)
        identity = (runtime.connection_identity, state.get('cwd'))
        revision = state.get('_goalRevision', 0)
    goal = value(runtime.rpc('thread/goal/get', {'threadId': tid}), tid)
    with runtime.lock:
        state = loaded(runtime, tid)
        if (runtime.connection_identity, state.get('cwd')) != identity:
            raise IPCError('目标所属连接已改变')
        if state.get('_goalRevision', 0) == revision:
            state = NativeSnapshot({**state, 'threadGoal': goal, '_goalUnknown': False})
            runtime.snapshots[tid] = state
        return {'goal': state.get('threadGoal')}


def discover(bridge, tid):
    bridge.assert_target(tid); ipc, generation = bridge.require()
    if hasattr(bridge, 'owner_service'):
        from carryon.owner.goal_control import session
        def authorized():
            with bridge.lock:
                bridge.check_generation(ipc, generation); bridge.assert_target(tid)
        with session(bridge, tid, authorized) as control:
            if control is not None:
                identity = control.runtime.connection_identity
                goal = value(control.runtime.rpc('thread/goal/get', {'threadId': tid}), tid)
                with bridge.lock:
                    if control.runtime.connection_identity != identity or not control.runtime.connected:
                        raise IPCError('目标控制读取所属连接已改变')
                    authorized(); control.project(goal)
                bridge.notify()
                return {'goal': goal}
    runtime = ipc if getattr(ipc, 'protocol', None) == 'codex-app-server' else None
    service = getattr(bridge, 'owner_service', None)
    if runtime is None and service is not None:
        with service.lock:
            entry = service.entries.get(tid)
            if entry and not any(entry.get(k) for k in ('suspended', 'conflict', 'disconnect')):
                runtime = entry['runtime']
    if runtime is None: raise IPCError('当前桌面会话不支持原生目标')
    result = read(runtime, tid)
    with bridge.lock:
        bridge.check_generation(ipc, generation); bridge.assert_target(tid)
    runtime.on_change()
    bridge.notify()
    return result


def request(tid, data):
    action = data['action']
    fields = {'requestId', 'action'} | ({'objective', 'status', 'tokenBudget'} if action == 'goal-set' else set())
    if set(data) - fields: raise ValueError('目标操作包含未支持字段')
    params = {'threadId': tid}
    if action == 'goal-clear': return 'thread/goal/clear', params
    if action == 'goal-pause': return 'thread/goal/set', {**params, 'status': 'paused'}
    if not any(key in data for key in ('objective', 'status', 'tokenBudget')): raise ValueError('请选择目标修改内容')
    if 'objective' in data:
        objective = data['objective']
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 16000: raise ValueError('目标描述为空或过长')
        params['objective'] = objective
    if 'status' in data:
        if data['status'] not in ('active', 'complete'): raise ValueError('目标状态只允许启动或完成；暂停使用goal-pause')
        params['status'] = data['status']
    if 'tokenBudget' in data:
        budget = data['tokenBudget']
        if type(budget) is not int or not 0 < budget <= 2**63 - 1: raise ValueError('目标预算必须为正整数')
        params['tokenBudget'] = budget
    return 'thread/goal/set', params


def dispatch(bridge, ipc, generation, job, data, authorize):
    tid = job['threadId']; attempted = False; replied = False; runtime = None; identity = None
    def authorized():
        bridge.check_generation(ipc, generation); bridge.assert_target(tid)
        if authorize: authorize()
    try:
        method, params = request(tid, data)
        if job.get('sideParentId'): raise IPCError('临时聊天不支持目标管理')
        if data['action'] != 'goal-set' and hasattr(bridge, 'owner_service'):
            from carryon.owner.goal_control import session as control_session
            with control_session(bridge, tid, authorized) as control:
                if control is not None:
                    runtime = control.runtime
                    identity = runtime.connection_identity
                    def controlled(write):
                        nonlocal attempted
                        with bridge.lock:
                            authorized()
                            def checked():
                                nonlocal attempted
                                if runtime.connection_identity != identity or not runtime.connected:
                                    raise IPCError('目标控制连接已改变')
                                bridge.journal.update(job['id'], state='dispatching')
                                attempted = True; write()
                            control.guard(checked)
                    try:
                        result = runtime.rpc(method, params, controlled); replied = True
                        goal = None if data['action'] == 'goal-clear' else value(result, tid)
                        if (data['action'] == 'goal-clear' and result.get('cleared') is not True
                                or data['action'] == 'goal-pause' and (goal is None or goal['status'] != 'paused')):
                            raise IPCError('原生目标控制回执未确认', uncertain=True)
                        with bridge.lock:
                            authorized()
                            if runtime.connection_identity != identity or not runtime.connected:
                                raise IPCError('目标控制回执所属连接已改变', uncertain=True)
                            control.project(goal)
                            bridge.journal.update(job['id'], state='completed', result=result, evidence='native-goal-response')
                    except Exception as exc:
                        if attempted and (replied or not isinstance(exc, IPCError) or exc.uncertain):
                            try: control.project(None, unknown=True)
                            except IPCError: pass
                        raise
                    bridge.notify()
                    return
        if getattr(ipc, 'protocol', None) == 'codex-app-server': session = nullcontext((ipc, lambda write: write()))
        elif hasattr(bridge, 'native_session'): session = bridge.native_session(tid, authorized, loaded_only=data['action'] != 'goal-set', submitted_turns=set(), track_future_turns=True)
        else: raise IPCError('当前桌面会话不支持原生目标')
        with session as target:
            if target is None: raise IPCError('目标操作需要已加载的原生会话')
            runtime, owner_guard = target
            with runtime._queue_lock(tid):
                read(runtime, tid)
                state = loaded(runtime, tid)
                identity = (runtime.connection_identity, state.get('cwd'))
                revision = state.get('_goalRevision', 0)
                def current():
                    state = loaded(runtime, tid)
                    if (runtime.connection_identity, state.get('cwd')) != identity:
                        raise IPCError('目标所属连接已改变', uncertain=attempted)
                    return state
                def guarded(write):
                    nonlocal attempted
                    with bridge.lock:
                        authorized()
                        def checked():
                            nonlocal attempted, revision
                            with runtime.lock:
                                state = current()
                                revision = state.get('_goalRevision', 0) + 1
                                runtime.snapshots[tid] = NativeSnapshot({**state, '_goalRevision': revision})
                                bridge.journal.update(job['id'], state='dispatching')
                                attempted = True; write()
                        owner_guard(checked)
                try:
                    result = runtime.rpc(method, params, guarded)
                    replied = True
                    goal = None if data['action'] == 'goal-clear' else value(result, tid)
                    if data['action'] == 'goal-clear' and result.get('cleared') is not True:
                        raise IPCError('原生目标清除尚未确认', uncertain=True)
                    if data['action'] == 'goal-pause' and (goal is None or goal['status'] != 'paused'):
                        raise IPCError('原生目标暂停尚未确认', uncertain=True)
                    with bridge.lock:
                        authorized()
                        def confirm():
                            with runtime.lock:
                                state = current()
                                if state.get('_goalRevision', 0) == revision:
                                    runtime.snapshots[tid] = NativeSnapshot({**state, 'threadGoal': goal, '_goalUnknown': False,
                                        '_goalRevision': revision + 1})
                                bridge.journal.update(job['id'], state='completed', result=result, evidence='native-goal-response')
                        owner_guard(confirm)
                except Exception as exc:
                    if attempted and (replied or not isinstance(exc, IPCError) or exc.uncertain):
                        with runtime.lock:
                            state = runtime.current(tid)
                            if state and (runtime.connection_identity, state.get('cwd')) == identity:
                                runtime.snapshots[tid] = NativeSnapshot({**state, '_goalUnknown': True,
                                    '_goalRevision': state.get('_goalRevision', 0) + 1})
                    raise
    except Exception as exc:
        uncertain = attempted and (replied or not isinstance(exc, IPCError) or exc.uncertain)
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
    if runtime: runtime.on_change()
    bridge.notify()
