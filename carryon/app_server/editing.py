"""Two native writes for a last-turn edit; callers own authority and receipts."""
from copy import deepcopy

from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.history_cache import NativeSnapshot


def refresh_retained(runtime, tid, thread):
    """Revert returns metadata only. Hydrate retained turns with buffered events."""
    from carryon.app_server.app_server import native_turn
    if thread.get('id') != tid: raise IPCError('原生回退结果属于其他会话')
    with runtime.load_lock:
        with runtime.lock:
            runtime.loading[tid] = []
        try:
            turns, cursor, seen = [], None, set()
            while True:
                page = runtime.rpc('thread/turns/list', {'threadId': tid, 'cursor': cursor,
                    'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
                turns.extend(native_turn(turn) for turn in page['data'])
                cursor = page.get('nextCursor')
                if not cursor: break
                if cursor in seen: raise IPCError('编辑后历史分页游标重复')
                seen.add(cursor)
            with runtime.lock:
                previous = runtime.current(tid)
                if previous is None or not runtime.connected: raise IPCError('编辑后会话连接已改变')
                restored = {**previous, 'threadMetadata': thread,
                    'cwd': thread['cwd'], 'turns': turns, 'threadRuntimeStatus': thread['status'],
                    'nativeQueue': []}
                restored.pop('_metadataOnly', None)
                runtime.snapshots[tid] = NativeSnapshot(restored)
                for event in runtime.loading.pop(tid): runtime._apply(event, tid)
        finally:
            with runtime.lock: runtime.loading.pop(tid, None)
    runtime.on_change()


def invalidate(runtime, tid):
    with runtime.lock:
        state = runtime.current(tid)
        if state is not None:
            runtime.snapshots[tid] = NativeSnapshot({**state, '_metadataOnly': True,
                'threadRuntimeStatus': {'type': 'notLoaded'}})
    runtime.on_change()


def edit_last(runtime, tid, turn_id, prompt, client_id, before_write, progress):
    """Never retries either write. before_write receives phase and a write closure."""
    runtime.require_account()
    with runtime._queue_lock(tid):
        state = runtime.current(tid)
        if not runtime.queue_idle(state): raise IPCError('编辑需要已确认空闲的会话')
        if state.get('threadMetadata', {}).get('historyMode') != 'paginated':
            raise IPCError('此会话不支持原生分页编辑')
        turns = state['turns']
        if not turns or turns[-1]['turnId'] != turn_id: raise IPCError('最后一轮已改变')
        user = next((i for i in reversed(turns[-1]['items']) if i.get('type') == 'userMessage'), None)
        if not user: raise IPCError('最后一轮没有可编辑的用户消息')
        content = user['content']
        if any(i.get('text_elements') for i in content if i.get('type') == 'text'):
            raise IPCError('带文本引用的消息请在原生客户端编辑')
        inputs = [{'type': 'text', 'text': prompt, 'text_elements': []}] + [deepcopy(i) for i in content if i['type'] != 'text']
        retained = [t['turnId'] for t in turns[:-1]]
        identity = (runtime.process, runtime.session_id)

        def guard(phase, expected):
            def guarded(write):
                if runtime.queue_snapshot(tid, refresh=True): raise IPCError('请先处理排队消息再编辑')
                from carryon.sessions.skills import guard_inputs
                skill_guard = guard_inputs(runtime, tid, inputs)
                def checked():
                    with runtime.lock:
                        current = runtime.current(tid)
                        if ((runtime.process, runtime.session_id) != identity or not runtime.connected
                                or not runtime.queue_idle(current)
                                or [t['turnId'] for t in current['turns']] != expected):
                            raise IPCError('编辑期间会话状态已改变')
                        if skill_guard: skill_guard(write)
                        else: write()
                before_write(phase, checked)
            return guarded

        try:
            result = runtime.rpc('thread/revert', {'threadId': tid, 'beforeTurnId': turn_id},
                                 guard('reverting', retained + [turn_id]))
        except IPCError as exc:
            if exc.uncertain: invalidate(runtime, tid)
            raise
        progress('reverted', {'revertedTurnId': turn_id})
        try:
            refresh_retained(runtime, tid, result['thread'])
        except Exception:
            invalidate(runtime, tid)
            raise
        try:
            result = runtime.rpc('turn/start', {'threadId': tid, 'clientUserMessageId': client_id, 'input': inputs},
                                 guard('starting', retained))
        except IPCError as exc:
            if exc.uncertain: invalidate(runtime, tid)
            raise
        runtime.record_started(tid, result['turn'])
        return result
