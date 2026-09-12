"""Bounded projections of immutable native snapshots; never used to authorize writes."""
import hashlib
import json
import threading
import uuid
import weakref
from collections import OrderedDict


class NativeSnapshot(dict):
    """Identity and revision travel together; patches never mutate this snapshot."""
    def __init__(self, value):
        super().__init__(value)
        self.history_revision = uuid.uuid4().hex


class TurnCache:
    def __init__(self, max_bytes=8 * 1024 * 1024):
        self.entries = OrderedDict()
        self.bytes = 0
        self.max_bytes = max_bytes
        self.lock = threading.RLock()

    def get(self, turn, position, build):
        key = (id(turn), position)
        with self.lock:
            previous = self.entries.get(key)
            if previous is not None and previous[0] is turn:
                self.entries.move_to_end(key)
                return previous[1]
        result = build(turn, position)
        size = len(json.dumps(turn, ensure_ascii=False).encode()) + len(json.dumps(result[0], ensure_ascii=False).encode())
        with self.lock:
            previous = self.entries.pop(key, None)
            if previous: self.bytes -= previous[2]
            if size <= self.max_bytes:
                self.entries[key] = (turn, result, size)
                self.bytes += size
            while self.bytes > self.max_bytes:
                _, previous = self.entries.popitem(last=False)
                self.bytes -= previous[2]
        return result

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.bytes = 0


class HistoryCache:
    def __init__(self, max_entries=8, max_bytes=16 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.entries = OrderedDict()
        self.bytes = 0
        self.generation = 0
        self.lock = threading.RLock()
        self.builders = weakref.WeakValueDictionary()
        self.turns = TurnCache()

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.bytes = 0
            self.generation += 1
            self.turns = TurnCache()

    def project(self, state, build, *, limit=None, segmented=False):
        key = (state['id'], limit) if limit else state['id']
        with self.lock:
            builder = self.builders.setdefault(key, threading.Lock())
        with builder:
            with self.lock:
                generation = self.generation
                turns = self.turns
                entry = self.entries.get(key)
                if entry is not None and (entry[0]() if isinstance(entry[0], weakref.ReferenceType) else entry[0]) is state:
                    self.entries.move_to_end(key)
                    return dict(entry[1])
            result = build(state, turn_cache=turns, limit=limit) if segmented else build(state)
            revision = getattr(state, 'history_revision', None)
            # Deterministic fallback also keeps oversized projections stable when
            # callers supply ordinary dictionaries instead of IPC snapshots.
            if revision is None:
                revision = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            result = {**result, 'historyRevision': revision + ':' + str(limit or 'all')}
            # IPC owns the full snapshot; retaining a display cache must not pin its
            # entire native history. Plain-dictionary callers still count both bodies.
            reference = weakref.ref(state) if isinstance(state, NativeSnapshot) else state
            size = len(json.dumps(result, ensure_ascii=False).encode())
            if not isinstance(state, NativeSnapshot):
                size += len(json.dumps(state, ensure_ascii=False).encode())
            with self.lock:
                if generation != self.generation:
                    return dict(result)
                previous = self.entries.pop(key, None)
                if previous:
                    self.bytes -= previous[2]
                if size <= self.max_bytes:
                    self.entries[key] = (reference, result, size)
                    self.bytes += size
                while len(self.entries) > self.max_entries or self.bytes > self.max_bytes:
                    _, previous = self.entries.popitem(last=False)
                    self.bytes -= previous[2]
            return dict(result)
