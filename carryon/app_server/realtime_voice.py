"""Native realtime lifecycle and bounded, transient PCM delivery."""
import base64
import binascii
import uuid
from collections import deque
from contextlib import nullcontext

from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.history_cache import NativeSnapshot

HELD = {'starting', 'active', 'stopping', 'unknown'}
MAX_AUDIO = 24000 * 2  # At most one second of mono PCM16 per input frame.
MAX_BUFFER = 4 * 1024 * 1024


def held(state):
    return (state or {}).get('voice', {}).get('state') in HELD


def project(runtime, tid, voice):
    state = runtime.current(tid)
    if not state or state.get('_metadataOnly'): raise IPCError('语音需要已加载的原生会话')
    runtime.snapshots[tid] = NativeSnapshot({**state, 'voice': voice})


def event(runtime, tid, method, params):
    """Called under runtime.lock; PCM never enters durable history or snapshots."""
    channel = runtime.voice_channels.get(tid)
    if channel is None or channel['connection'] != runtime.session_id: return False
    state = runtime.current(tid)
    voice = dict((state or {}).get('voice') or {})
    if voice.get('id') != channel['id']: return False
    changed = False
    if method == 'thread/realtime/started':
        if params.get('realtimeSessionId') != channel['id']: return False
        voice['started'] = True; changed = True
        if voice.get('state') in ('starting', 'unknown') and not voice.get('stopRequested'):
            voice.update(state='active'); voice.pop('error', None)
    elif method == 'thread/realtime/closed':
        voice.update(state='closed', closed=True, reason=params.get('reason')); changed = True
    elif method == 'thread/realtime/error' and voice.get('state') != 'closed':
        voice.update(state='unknown', error=params.get('message') or params.get('error') or '原生语音发生错误'); changed = True
    if changed:
        channel['revision'] = channel.get('revision', 0) + 1
        project(runtime, tid, voice)
    if method in ('thread/realtime/outputAudio/delta', 'thread/realtime/transcript/delta', 'thread/realtime/transcript/done'):
        if voice.get('state') not in ('active', 'stopping'): return changed
        payload = {'audio': params.get('audio')} if '/outputAudio/' in method else {k: params[k] for k in ('role', 'delta', 'text') if k in params}
        size = len(str(payload).encode())
        if size > MAX_BUFFER: return changed
        channel['sequence'] += 1
        row = {'sequence': channel['sequence'], 'type': method.rsplit('/', 2)[-2] + '/' + method.rsplit('/', 1)[-1], **payload}
        channel['events'].append((row, size)); channel['bytes'] += size
        while len(channel['events']) > 256 or channel['bytes'] > MAX_BUFFER:
            _, removed = channel['events'].popleft(); channel['bytes'] -= removed
    return changed


def channel(runtime, tid, identifier=None):
    state = runtime.current(tid)
    if not runtime.connected or not state or state.get('_metadataOnly'): raise IPCError('语音所属原生连接已断开')
    voice = state.get('voice') or {'state': 'closed'}
    current = runtime.voice_channels.get(tid)
    if identifier is not None and (not current or current['id'] != identifier or current['connection'] != runtime.session_id):
        raise IPCError('语音会话已改变，请重新查看状态')
    return voice, current


def read(bridge, tid, after=0):
    from carryon.sessions.skills import discover_runtime
    runtime, ipc, generation = discover_runtime(bridge, tid)
    with bridge.lock, runtime.lock:
        bridge.check_generation(ipc, generation)
        voice, current = channel(runtime, tid)
        events = [row for row, _ in current['events'] if row['sequence'] > after] if current else []
        return {'voice': dict(voice), 'events': events, 'sequence': current['sequence'] if current else 0,
                'dropped': bool(current and current['events'] and after < current['events'][0][0]['sequence'] - 1)}


def dispatch(bridge, ipc, generation, job, data, authorize):
    tid = job['threadId']; action = data['action']; attempted = False; replied = False; runtime = None; previous_voice = None; identity = None; voice_id = None; event_revision = None
    def authorized():
        bridge.check_generation(ipc, generation); bridge.assert_target(tid)
        if authorize: authorize()
    try:
        fields = {'action', 'requestId'} | ({'voiceId'} if action == 'voice-stop' else set())
        if set(data) - fields or job.get('sideParentId'): raise ValueError('语音操作包含未支持字段或目标')
        if getattr(ipc, 'protocol', None) == 'codex-app-server': session = nullcontext((ipc, lambda write: write()))
        elif hasattr(bridge, 'native_session'): session = bridge.native_session(tid, authorized, loaded_only=True, submitted_turns=set())
        else: raise IPCError('当前会话没有原生语音入口')
        with session as target:
            if target is None: raise IPCError('语音需要已加载的原生会话')
            runtime, owner_guard = target
            with runtime._queue_lock(tid):
                identity = (runtime.process, runtime.session_id)
                voice_id = str(uuid.uuid4()) if action == 'voice-start' else data.get('voiceId')
                def guarded(write):
                    nonlocal attempted
                    with bridge.lock:
                        authorized()
                        def checked():
                            nonlocal attempted, previous_voice, event_revision
                            with runtime.lock:
                                if (runtime.process, runtime.session_id) != identity: raise IPCError('原生语音连接已改变')
                                voice, _ = channel(runtime, tid, voice_id if action == 'voice-stop' else None)
                                previous_voice = dict(voice)
                                if action == 'voice-start':
                                    if voice.get('state') in HELD: raise IPCError('已有语音会话尚未关闭，请先核对或结束')
                                    runtime.voice_channels[tid] = {'id': voice_id, 'connection': runtime.session_id, 'sequence': 0,
                                        'events': deque(), 'bytes': 0, 'inputSequence': 0, 'revision': 0}
                                    project(runtime, tid, {'id': voice_id, 'state': 'starting'})
                                else:
                                    if not isinstance(voice_id, str) or voice.get('state') not in HELD: raise IPCError('语音已结束或身份不匹配')
                                    project(runtime, tid, {**voice, 'state': 'stopping', 'stopRequested': True})
                                event_revision = runtime.voice_channels[tid].get('revision', 0)
                                bridge.journal.update(job['id'], state='dispatching', result={'voiceId': voice_id, 'connection': runtime.session_id}); attempted = True; write()
                        owner_guard(checked)
                params = {'threadId': tid}
                if action == 'voice-start': params.update(realtimeSessionId=voice_id, version='v2', outputModality='audio', transport={'type': 'websocket'})
                runtime.rpc('thread/realtime/' + ('start' if action == 'voice-start' else 'stop'), params, guarded)
                replied = True
                with bridge.lock:
                    authorized()
                    def confirm():
                        with runtime.lock:
                            if (runtime.process, runtime.session_id) != identity or not runtime.connected: raise IPCError('语音回执所属连接已改变', uncertain=True)
                            channel(runtime, tid, voice_id)
                            bridge.journal.update(job['id'], state='completed', result={'voiceId': voice_id, 'requestAccepted': True}, evidence='native-realtime-request-response')
                    owner_guard(confirm)
    except Exception as exc:
        uncertain = attempted and (replied or not isinstance(exc, IPCError) or exc.uncertain)
        if runtime and attempted:
            with runtime.lock:
                state = runtime.current(tid)
                if state and held(state) and (runtime.process, runtime.session_id) == identity and state['voice'].get('id') == voice_id and runtime.voice_channels.get(tid, {}).get('revision', 0) == event_revision:
                    project(runtime, tid, {**state['voice'], 'state': 'unknown', 'error': str(exc)} if uncertain else (previous_voice or {'state': 'closed'}))
        bridge.journal.update(job['id'], state='uncertain' if uncertain else 'failed', error=str(exc))
    if runtime: runtime.on_change()
    bridge.notify()


def append_audio(bridge, tid, data, authorize=None):
    if set(data) != {'voiceId', 'sequence', 'audio'}: raise ValueError('音频帧字段无效')
    sequence = data['sequence']; audio = data['audio']
    if type(sequence) is not int or sequence < 1 or not isinstance(audio, dict) or set(audio) != {'data', 'sampleRate', 'numChannels', 'samplesPerChannel'}:
        raise ValueError('音频帧格式无效')
    if (type(audio['sampleRate']) is not int or audio['sampleRate'] != 24000 or type(audio['numChannels']) is not int or audio['numChannels'] != 1
            or type(audio['samplesPerChannel']) is not int or not 0 < audio['samplesPerChannel'] <= 24000
            or not isinstance(audio['data'], str) or len(audio['data']) > 64000): raise ValueError('音频必须为 24 kHz 单声道 PCM16LE')
    try: raw = base64.b64decode(audio['data'], validate=True)
    except (ValueError, binascii.Error): raise ValueError('音频编码无效') from None
    if len(raw) != audio['samplesPerChannel'] * 2 or len(raw) > MAX_AUDIO: raise ValueError('音频样本数不匹配')
    bridge.assert_target(tid); ipc, generation = bridge.require()
    def authorized():
        bridge.check_generation(ipc, generation); bridge.assert_target(tid)
        if authorize: authorize()
    if getattr(ipc, 'protocol', None) == 'codex-app-server': session = nullcontext((ipc, lambda write: write()))
    elif hasattr(bridge, 'native_session'): session = bridge.native_session(tid, authorized, loaded_only=True, submitted_turns=set())
    else: raise IPCError('当前会话没有原生语音入口')
    with session as target:
        if target is None: raise IPCError('语音需要已加载的原生会话')
        runtime, owner_guard = target
        identity = (runtime.process, runtime.session_id)
        with runtime._queue_lock(tid):
            def guarded(write):
                with bridge.lock:
                    authorized()
                    def checked():
                        with runtime.lock:
                            if (runtime.process, runtime.session_id) != identity: raise IPCError('原生语音连接已改变')
                            voice, current = channel(runtime, tid, data['voiceId'])
                            if voice.get('state') != 'active': raise IPCError('语音尚未启动或已停止')
                            if sequence != current['inputSequence'] + 1: raise IPCError('音频序号不连续；不会自动重发')
                            current['inputSequence'] = sequence; write()
                    owner_guard(checked)
            runtime.rpc('thread/realtime/appendAudio', {'threadId': tid, 'audio': audio}, guarded)
    return {'accepted': True, 'sequence': sequence}


def recover(bridge, job):
    """Only this native generation's lifecycle notifications resolve a lost RPC receipt."""
    from carryon.sessions.skills import discover_runtime
    from carryon.errors import BridgeError
    try:
        runtime, ipc, generation = discover_runtime(bridge, job['threadId'])
        receipt = job.get('result') or {}
        with bridge.lock, runtime.lock:
            bridge.check_generation(ipc, generation)
            voice, current = channel(runtime, job['threadId'], receipt.get('voiceId'))
            if (not current or receipt.get('connection') != runtime.session_id or current['id'] != receipt.get('voiceId')): return job
            confirmed = voice.get('started') if job['kind'] == 'operation:voice-start' else voice.get('closed')
            if confirmed:
                return bridge.journal.update(job['id'], expected=job, state='completed', error=None,
                    result={'voiceId': current['id'], 'requestAccepted': True}, evidence='native-realtime-lifecycle-notification')
    except (IPCError, BridgeError, ValueError): pass
    return job
