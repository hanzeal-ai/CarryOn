"""Read-only native persisted display events. Never resumes a thread or authorizes writes."""
import json
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .history_cache import NativeSnapshot
from .timeline import FIELDS


def camel(key):
    return re.sub(r'_([a-z])', lambda m: m[1].upper(), key)


def native_item(item):
    kind = item.get('type', '')
    kind = kind[:1].lower() + kind[1:]
    result = {camel(k): v for k, v in item.items()}
    result['type'] = kind
    if kind == 'reasoning':
        result = {'id': item.get('id'), 'type': kind, 'summary': item.get('summary_text', item.get('summary', [])), 'completed': True}
    elif kind in ('agentMessage', 'userMessage'):
        content = item.get('content', [])
        parts = [{**p, 'type': p.get('type', '')[:1].lower() + p.get('type', '')[1:]} for p in content if isinstance(p, dict) and p.get('type') in ('Text', 'text', 'Image', 'image', 'LocalImage', 'localImage')]
        if kind == 'agentMessage':
            result['text'] = item.get('text') or '\n'.join(p.get('text', '') for p in parts if p['type'] == 'text')
        else:
            result['content'] = parts
    elif kind == 'commandExecution':
        command = item.get('command', '')
        result['command'] = ' '.join(command) if isinstance(command, list) else command
        cwd = item.get('cwd', '')
        result['cwd'] = unquote(urlsplit(cwd).path) if cwd.startswith('file://') else cwd
        result['commandActions'] = item.get('parsed_cmd', [])
    if kind == 'collabAgentToolCall':
        result['tool'] = {'spawn_agent': 'spawnAgent', 'send_input': 'sendInput', 'resume_agent': 'resumeAgent', 'close_agent': 'closeAgent'}.get(result.get('tool'), result.get('tool'))
    # Projection whitelist removes runtime-only context, raw reasoning and encrypted data.
    return {k: v for k, v in result.items() if k in {'id', 'type', 'phase', 'status', 'completed'} | set(FIELDS.get(kind, '').split())}


def response_message(payload, identifier):
    parts = [{'type': 'text', 'text': p['text']} for p in payload.get('content', [])
             if p.get('type') in ('input_text', 'output_text', 'text') and isinstance(p.get('text'), str)]
    if payload.get('role') == 'user':
        return {'type': 'userMessage', 'id': identifier, 'content': parts}
    return {'type': 'agentMessage', 'id': identifier,
            'text': '\n'.join(p['text'] for p in parts), 'phase': payload.get('phase')}


class RolloutIndex:
    """Append-only byte offsets. Large tool outputs are read only for the requested page."""
    def __init__(self, row, home):
        self.path = Path(row['rollout_path']).resolve()
        if not self.path.is_relative_to(home) or not self.path.is_file():
            raise ValueError('本地会话历史不可用')
        self.row = row
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.position = 0
        self.fingerprint = None
        self.identity = None
        self.turns = {}
        self.records = {}
        self.active = None
        self.spawned = set()
        self.revision = uuid.uuid4().hex
        self.cached = None
        self.scanned_bytes = 0

    def turn(self, tid):
        return self.turns.setdefault(tid, {'turnId': tid, 'status': 'unknown', 'params': {}})

    def update(self):
        info = self.path.stat()
        fingerprint = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        if self.fingerprint == fingerprint: return
        identity = fingerprint[:2]
        if self.identity != identity or info.st_size < self.position or (self.fingerprint and info.st_size <= self.fingerprint[3]):
            self.reset()
        self.identity = identity
        with self.path.open('rb') as stream:
            stream.seek(self.position)
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line or not line.endswith(b'\n'): break
                try: record = json.loads(line)
                except (ValueError, UnicodeDecodeError): raise ValueError('会话历史包含损坏记录')
                self.observe(record, offset)
                self.position = stream.tell()
                self.scanned_bytes += len(line)
        self.fingerprint = fingerprint
        self.revision = uuid.uuid4().hex
        self.cached = None

    def observe(self, record, offset):
        payload = record.get('payload', {})
        if not isinstance(payload, dict): return
        category, kind = record.get('type'), payload.get('type')
        if category == 'event_msg':
            tid = payload.get('turn_id', self.active)
            if kind == 'task_started' and tid:
                self.active = tid
                t = self.turn(tid); t['status'] = 'inProgress'
                if isinstance(payload.get('started_at'), (int, float)): t['turnStartedAtMs'] = payload['started_at'] * 1000
            elif kind == 'item_completed' and tid and payload.get('thread_id', self.row['id']) == self.row['id']:
                item = payload.get('item', {})
                if item.get('phase') == 'analysis' or item.get('type') in ('HookPrompt', 'hookPrompt'): return
                self.turn(tid)
                identifier = item.get('id') or str(offset)
                self.records[(tid, identifier)] = (offset, True)
                if item.get('type') in ('CollabAgentToolCall', 'collabAgentToolCall'):
                    native = native_item(item)
                    if native.get('tool') == 'spawnAgent' and native.get('senderThreadId') == self.row['id']:
                        self.spawned.update(t for t in native.get('receiverThreadIds', []) if isinstance(t, str))
            elif kind in ('task_complete', 'turn_aborted') and tid:
                t = self.turn(tid); t['status'] = 'completed' if kind == 'task_complete' else 'interrupted'
                if isinstance(payload.get('duration_ms'), (int, float)): t['durationMs'] = payload['duration_ms']
        elif category == 'turn_context' and payload.get('turn_id'):
            self.turn(payload['turn_id'])['params'].update({k: payload[k] for k in ('model', 'effort') if k in payload})
        elif (self.row.get('history_mode', 'legacy') == 'legacy' and category == 'response_item'
              and kind == 'message' and payload.get('role') in ('user', 'assistant') and payload.get('phase') != 'analysis'):
            # Legacy history stores visible messages as response items. Paginated
            # history must use canonical UserMessage events instead of model inputs.
            if self.active is None:
                self.active = 'legacy:' + str(offset)
            self.turn(self.active)
            identifier = payload.get('id') or str(offset)
            self.records.setdefault((self.active, identifier), (offset, False))
        # Raw user-role model inputs also contain injected runtime/inherited context.
        # Only canonical UserMessage display events establish visible user input.
        # Do not guess visibility from text markers: users may legitimately quote them.
        elif category == 'response_item' and self.active and kind == 'message' and payload.get('role') == 'assistant' and payload.get('phase') != 'analysis':
            identifier = payload.get('id') or str(offset)
            self.records.setdefault((self.active, identifier), (offset, False))

    def snapshot(self, limit=None):
        with self.lock:
            self.update()
            if self.cached and self.cached[0] == limit: return self.cached[1]
            entries = list(self.records.items())
            total = len(entries)
            if limit: entries = entries[-limit:]
            selected = {key[0] for key, _ in entries}
            states = {tid: {**meta, 'params': dict(meta.get('params', {})), 'items': []} for tid, meta in self.turns.items() if tid in selected}
            with self.path.open('rb') as stream:
                for (tid, identifier), (offset, canonical) in entries:
                    stream.seek(offset)
                    try: payload = json.loads(stream.readline())['payload']
                    except (ValueError, KeyError): raise ValueError('会话历史在读取时发生变化，请重试')
                    item = native_item(payload['item']) if canonical else response_message(payload, identifier)
                    if canonical and isinstance(payload.get('started_at_ms'), (int, float)) and isinstance(payload.get('completed_at_ms'), (int, float)):
                        item['durationMs'] = max(0, payload['completed_at_ms'] - payload['started_at_ms'])
                    states[tid]['items'].append(item)
            state = NativeSnapshot({'id': self.row['id'], 'title': self.row.get('name') or self.row.get('title', ''), 'cwd': self.row.get('cwd', ''),
                                    'turns': list(states.values()), 'threadRuntimeStatus': {'type': 'notLoaded'}, 'requests': []})
            state.history_revision = self.revision
            latest = next(reversed(self.turns.values()), {}).get('params', {})
            state['latestModel'] = latest.get('model') or self.row.get('model')
            state['latestReasoningEffort'] = latest.get('effort') or self.row.get('reasoning_effort')
            if limit:
                state['rolloutWindow'] = {'limit': limit, 'total': total, 'hasMore': total > limit, 'unit': 'items'}
                state['earlierDurationMs'] = sum(t.get('durationMs', 0) for tid, t in self.turns.items() if tid not in selected)
            # Retain only one materialized page. The index itself contains no output bodies.
            if len(json.dumps(state, ensure_ascii=False).encode()) <= 2 * 1024 * 1024:
                self.cached = (limit, state)
            return state
