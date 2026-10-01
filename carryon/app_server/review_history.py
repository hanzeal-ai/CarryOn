"""Reconcile native review worker events with canonical persisted turns."""
import threading

from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.history_cache import NativeSnapshot


def schedule(runtime, tid, completed_id):
    with runtime.lock:
        state = runtime.current(tid)
        identity = (runtime.process, runtime.session_id)
        if not state or state.get('_metadataOnly') or runtime.review_refreshing.get(tid) == identity: return
        completed = next((turn for turn in state['turns'] if turn['turnId'] == completed_id), None)
        if (not completed or not any(item.get('type') == 'enteredReviewMode' for item in completed['items'])
                or not any(turn['status'] == 'inProgress' for turn in state['turns'])): return
        runtime.review_refreshing[tid] = identity
    threading.Thread(target=refresh, args=(runtime, tid, identity), daemon=True, name='native-review-history').start()


def refresh(runtime, tid, identity):
    from carryon.app_server.app_server import native_turn
    completions = []
    def replay(buffered):
        for event in buffered:
            runtime._apply(event, tid)
            if event['method'] == 'turn/completed': completions.append(event['params']['turn']['id'])
    try:
        with runtime._queue_lock(tid), runtime.load_lock:
            with runtime.lock:
                if (runtime.process, runtime.session_id) != identity or not runtime.connected: return
                runtime.loading[tid] = []
            try:
                thread = runtime.rpc('thread/read', {'threadId': tid, 'includeTurns': False})['thread']
                if thread['id'] != tid: raise IPCError('审查历史返回其他会话')
                turns, cursor, seen = [], None, set()
                while True:
                    page = runtime.rpc('thread/turns/list', {'threadId': tid, 'cursor': cursor,
                        'sortDirection': 'asc', 'limit': 100, 'itemsView': 'full'})
                    turns.extend(native_turn(turn) for turn in page['data'])
                    cursor = page.get('nextCursor')
                    if not cursor: break
                    if cursor in seen: raise IPCError('原生历史分页游标重复')
                    seen.add(cursor)
                with runtime.lock:
                    previous = runtime.current(tid)
                    if previous is None or (runtime.process, runtime.session_id) != identity or not runtime.connected: return
                    runtime.snapshots[tid] = NativeSnapshot({**previous, 'threadMetadata': thread,
                        'cwd': thread['cwd'], 'turns': turns, 'threadRuntimeStatus': thread['status']})
                    replay(runtime.loading.pop(tid))
            finally:
                with runtime.lock:
                    buffered = runtime.loading.pop(tid, [])
                    if (runtime.process, runtime.session_id) == identity and runtime.connected:
                        replay(buffered)
    except Exception:
        with runtime.lock:
            state = runtime.current(tid)
            if state is not None and (runtime.process, runtime.session_id) == identity:
                runtime.snapshots[tid] = NativeSnapshot({**state, '_metadataOnly': True,
                    'threadRuntimeStatus': {'type': 'notLoaded'}})
    finally:
        with runtime.lock:
            if runtime.review_refreshing.get(tid) == identity: runtime.review_refreshing.pop(tid)
        runtime.on_change()
        # Only newly buffered terminal events can request another read. There is
        # no polling loop when canonical history remains unavailable or unchanged.
        if (runtime.process, runtime.session_id) == identity:
            for completed_id in completions: schedule(runtime, tid, completed_id)
