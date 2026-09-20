"""Codex desktop IPC adapter, verified against desktop 26.901.51231.

This is NOT the public app-server JSON-RPC transport. No socket replacement.
"""
import json
import socket
import stat
import subprocess
import sys
import os
import struct
import threading
import time
import uuid
import weakref

from .patches import apply_patches
from .history_cache import NativeSnapshot


class IPCError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class DesktopIPC:
    MAX_FRAME = 32 * 1024 * 1024

    def __init__(self, path):
        self.path = str(path)
        self.sock = None
        self.client_id = "initializing-client"
        self.pending = {}
        self.snapshots = {}
        self.following = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.snapshot_locks = weakref.WeakValueDictionary()
        self.on_change = lambda: None
        self.on_read = lambda tid: None
        self.resyncing = set()
        self.watchers = {}
        from .events import Events
        self.events = Events(self)

    @property
    def connected(self):
        return self.sock is not None

    def connect(self):
        info = os.stat(self.path)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise IPCError("Socket 类型或所有者不符合要求")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(self.path)
        sock.settimeout(None)
        self.sock = sock
        threading.Thread(target=self._reader, args=(sock,), daemon=True).start()
        try:
            result = self.request("initialize", {"clientType": "carryon"})
            self.client_id = result["result"]["clientId"]
        except Exception:
            self.close()
            raise

    def _write(self, message):
        payload = json.dumps(message, ensure_ascii=False).encode()
        if len(payload) > self.MAX_FRAME:
            raise IPCError("请求过大")
        with self.write_lock:
            sock = self.sock
            if sock is None:
                raise IPCError("Codex socket 已断开")
            sock.sendall(struct.pack("<I", len(payload)) + payload)

    def request(self, method, params, version=0, target=None, before_send=None, timeout_ms=15000):
        request_id = str(uuid.uuid4())
        waiter = {"event": threading.Event()}
        with self.lock:
            self.pending[request_id] = waiter
        message = {"type": "request", "requestId": request_id,
                   "sourceClientId": self.client_id, "version": version,
                   "method": method, "params": params, "timeoutMs": timeout_ms}
        if target:
            message["targetClientId"] = target
        attempted = False
        try:
            if before_send:
                # Caller owns the gate and durably records dispatch before socket I/O.
                before_send(lambda: self._write(message))
                attempted = True
            else:
                attempted = True
                self._write(message)
            if not waiter["event"].wait(timeout_ms / 1000 + 3):
                raise IPCError("Codex 响应超时；不要自动重发", uncertain=True)
            if "error" in waiter:
                raise IPCError(waiter["error"], uncertain=attempted)
            response = waiter["response"]
            if response.get("resultType") != "success":
                error = response.get("error", "Codex 拒绝请求")
                # Routing failure proves no handler received the mutation.
                raise IPCError(error, uncertain=error not in (
                    "no-client-found", "request-version-mismatch", "no-handler-for-request"))
            return response
        except OSError as exc:
            raise IPCError("Socket 写入或读取失败", uncertain=True) from exc
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def owner(self, thread_id, timeout_ms=15000):
        response = self.request("thread-owner-discovery", {
            "hostId": "local", "conversationId": thread_id}, version=1, timeout_ms=timeout_ms)
        return response["handledByClientId"]

    def _snapshot_lock(self, thread_id):
        with self.lock:
            return self.snapshot_locks.setdefault(thread_id, threading.Lock())

    def snapshot(self, thread_id):
        with self._snapshot_lock(thread_id):
            return self._snapshot(thread_id)

    def sidebar_snapshot(self, thread_id):
        # Discovery for unloaded threads must not hold the full-history lock.
        with self.lock:
            state = self.current(thread_id)
            if state is not None and not state.get('_metadataOnly') and thread_id in self.following:
                return self.following[thread_id], state
        owner = self.owner(thread_id, timeout_ms=1500)
        with self._snapshot_lock(thread_id):
            state = self.current(thread_id)
            if state is not None and not state.get('_metadataOnly'):
                return owner, state
            return self._snapshot(thread_id, owner)

    def wake_snapshot(self, thread_id, *, before_open):
        """Ask the desktop to load an existing task, then read its native state."""
        from .catalog import valid_id
        valid_id(thread_id)
        if sys.platform != 'darwin':
            raise IPCError('当前平台不支持唤起 Codex 会话')
        before_open()
        try:
            subprocess.run(['open', '-g', 'codex://threads/' + thread_id],
                           check=True, capture_output=True, timeout=3)
        except (OSError, subprocess.SubprocessError) as exc:
            raise IPCError('无法唤起 Codex 会话') from exc
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            before_open()
            try:
                owner = self.owner(thread_id, timeout_ms=500)
                with self._snapshot_lock(thread_id):
                    owner, state = self._snapshot(thread_id, owner)
                if (state.get('threadRuntimeStatus') or {}).get('type') != 'notLoaded':
                    return owner, state
            except IPCError:
                if not self.connected: raise
            with self.changed:
                self.changed.wait(timeout=min(.25, max(0, deadline - time.monotonic())))
        raise IPCError('唤起后仍未取得会话实时状态，请稍后重试')

    def _snapshot(self, thread_id, owner=None):
        owner = owner or self.owner(thread_id)
        with self.lock:
            expired = [t for t in self.following if not self.watchers.get(t) and t != thread_id
                       and not self._snapshot_lock(t).locked()][:-3]
        for old in expired:
            with self.lock:
                if self.watchers.get(old) or self._snapshot_lock(old).locked():
                    continue
                old_owner = self.following.pop(old, None)
                self.snapshots.pop(old, None)
            if old_owner:
                self._write({"type": "broadcast", "method": "thread-stream-following-changed",
                    "sourceClientId": self.client_id, "version": 1, "targetClientIds": [old_owner],
                    "params": {"hostId": "local", "conversationId": old, "following": False}})
        with self.lock:
            self.snapshots.pop(thread_id, None)
            if self.following.get(thread_id) != owner:
                self.events.queues.pop(thread_id, None)
            self.following[thread_id] = owner
        self._write({"type": "broadcast", "method": "thread-stream-following-changed",
                     "sourceClientId": self.client_id, "version": 1,
                     "targetClientIds": [owner], "params": {
                         "hostId": "local", "conversationId": thread_id, "following": True}})
        response = self.request("thread-follower-load-complete-history",
                                {"conversationId": thread_id}, 1, owner)
        revision = response["result"].get("revision")
        deadline = time.monotonic() + 5
        with self.changed:
            while time.monotonic() < deadline:
                snapshot = self.snapshots.get(thread_id)
                if snapshot and (revision is None or snapshot[0] >= revision):
                    return owner, snapshot[1]
                self.changed.wait(max(0, deadline - time.monotonic()))
        raise IPCError("未收到完整会话快照，请在 Codex App 打开该会话后重试")

    def start(self, thread_id, text, owner, client_message_id, before_send, images=None):
        response = self.request("thread-follower-start-turn", {
            "conversationId": thread_id,
            "turnStart": {"request": {"threadId": thread_id,
                "clientUserMessageId": client_message_id,
                "input": ([{"type": "text", "text": text, "text_elements": []}] if text else [])+[{"type":"image","url":url} for url in (images or [])]},
                "context": {"inheritThreadSettings": True}}}, 2, owner, before_send)
        return response["result"]["result"]["turn"]

    @staticmethod
    def _exact(sock, size):
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise EOFError("socket closed")
            data.extend(chunk)
        return bytes(data)

    def _reader(self, sock):
        try:
            while True:
                length = struct.unpack("<I", self._exact(sock, 4))[0]
                if not 0 < length <= self.MAX_FRAME:
                    raise IPCError("不支持的 IPC 帧大小")
                message = json.loads(self._exact(sock, length))
                kind = message.get("type")
                if kind == "response":
                    with self.lock:
                        waiter = self.pending.get(message.get("requestId"))
                        if waiter:
                            waiter["response"] = message
                            waiter["event"].set()
                elif kind == "client-discovery-request":
                    self._write({"type": "client-discovery-response",
                                 "requestId": message["requestId"], "response": {"canHandle": False}})
                elif kind == "broadcast" and message.get("method") == "client-status-changed":
                    params = message.get("params", {})
                    with self.lock:
                        owner_left = (params.get("status") == "disconnected"
                                      and params.get("clientId") in self.following.values())
                    if owner_left:
                        raise IPCError("会话所属客户端已断开，请重新开启桥接")
                elif kind == "broadcast" and message.get("method") == "thread-stream-state-changed":
                    params = message.get("params", {})
                    thread_id = params.get("conversationId")
                    change = params.get("change", {})
                    self._change(message, params, thread_id, change)
                elif kind == "broadcast":
                    self.events.handle(message)
        except (OSError, EOFError, ValueError, KeyError, IPCError):
            pass
        finally:
            self.close(sock)

    def watch(self, thread_id):
        with self.lock:
            self.watchers[thread_id] = self.watchers.get(thread_id, 0) + 1

    def unwatch(self, thread_id):
        with self.lock:
            count = self.watchers.get(thread_id, 0)
            if count > 1:
                self.watchers[thread_id] = count - 1
            else:
                self.watchers.pop(thread_id, None)

    def current(self, thread_id):
        with self.lock:
            snapshot = self.snapshots.get(thread_id)
            return snapshot[1] if snapshot else None

    def _change(self, message, params, thread_id, change):
        resync = False
        with self.changed:
            if (message.get("version") != 11 or params.get("hostId") != "local"
                    or thread_id not in self.following
                    or self.following[thread_id] != message.get("sourceClientId")):
                return
            previous = self.snapshots.get(thread_id)
            revision = change.get("revision")
            if type(revision) is not int:
                return
            if previous and revision <= previous[0]:
                return
            if change.get("type") == "snapshot":
                state = change.get("conversationState")
                if not isinstance(state, dict) or state.get("id") != thread_id:
                    return
                self.snapshots[thread_id] = (revision, NativeSnapshot(state))
            elif change.get("type") == "patches":
                try:
                    if not previous or previous[0] != change.get("baseRevision"):
                        raise ValueError("Revision gap")
                    state = apply_patches(previous[1], change["patches"])
                    if state.get("id") != thread_id:
                        raise ValueError("Thread changed")
                    self.snapshots[thread_id] = (revision, NativeSnapshot(state))
                except (ValueError, KeyError, TypeError, IndexError):
                    self.snapshots.pop(thread_id, None)
                    resync = thread_id not in self.resyncing
                    self.resyncing.add(thread_id)
            else:
                return
            self.changed.notify_all()
        self.on_change()
        if resync:
            threading.Thread(target=self._resync, args=(thread_id,), daemon=True).start()

    def _resync(self, thread_id):
        try:
            self.snapshot(thread_id)
        except (IPCError, OSError):
            self.close()
        finally:
            with self.lock:
                self.resyncing.discard(thread_id)
            self.on_change()

    def close(self, expected=None):
        with self.lock:
            if expected is not None and self.sock is not expected:
                return
            sock, self.sock = self.sock, None
            self.snapshots.clear()
            self.following.clear()
            self.events.clear()
            for waiter in self.pending.values():
                waiter["error"] = "Codex socket 已断开；请求结果可能未知"
                waiter["event"].set()
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        self.on_change()
