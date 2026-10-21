"""Bounded, resumable attachments; client paths never select a server directory."""
import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import stat
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path

from carryon.contracts import digest, text, validate_request_id
from carryon.errors import BridgeError

LIMITS = {'chunkBytes': 49152, 'maxEntries': 100,
          'maxFileBytes': 20 * 1024 * 1024, 'maxTotalBytes': 50 * 1024 * 1024}
MAX_STORAGE_BYTES = 1024 * 1024 * 1024
IDENTIFIER = re.compile(r'[0-9a-f]{32}')
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def fields(data, allowed):
    if not isinstance(data, dict) or set(data) - allowed - {'action'}:
        raise ValueError('上传请求包含不支持的字段')
    if len(json.dumps(data, ensure_ascii=False).encode()) > 100000:
        raise ValueError('上传请求过大')


def relative_path(value):
    if not isinstance(value, str):
        raise ValueError('附件路径无效')
    value = unicodedata.normalize('NFC', value)
    parts = value.split('/')
    if (not value or len(value.encode()) > 512 or '\\' in value
            or any(ord(c) < 32 or ord(c) == 127 or c in '\u2028\u2029' for c in value)
            or any(p in ('', '.', '..') or ':' in p or p != p.strip()
                   or p.endswith('.') or len(p.encode()) > 255 for p in parts)):
        raise ValueError('附件路径无效')
    return value


def manifest(data):
    name = relative_path(data.get('name'))
    kind = data.get('kind')
    entries = data.get('entries')
    if '/' in name or kind not in ('file', 'directory'):
        raise ValueError('附件名称或类型无效')
    if not isinstance(entries, list) or not 1 <= len(entries) <= LIMITS['maxEntries']:
        raise ValueError('每个附件最多包含 100 个文件或目录')
    result, aliases, total = {}, set(), 0
    for item in entries:
        if not isinstance(item, dict) or item.get('kind') not in ('file', 'directory'):
            raise ValueError('附件清单无效')
        path = relative_path(item.get('path'))
        fields = {'path', 'kind'} | ({'size', 'sha256'} if item['kind'] == 'file' else set())
        if set(item) != fields or path.split('/')[0] != name or path.casefold() in aliases:
            raise ValueError('附件路径重复或不属于所选附件')
        aliases.add(path.casefold())
        entry = {**item, 'path': path}
        if item['kind'] == 'file':
            if (type(item['size']) is not int or not 0 <= item['size'] <= LIMITS['maxFileBytes']
                    or not isinstance(item['sha256'], str)
                    or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
                raise ValueError('文件大小或 SHA256 无效')
            total += item['size']
        result[path] = entry
    if total > LIMITS['maxTotalBytes']:
        raise ValueError('附件总大小不能超过 50 MiB')
    if name not in result or result[name]['kind'] != kind or kind == 'file' and len(result) != 1:
        raise ValueError('附件清单缺少所选文件或目录')
    for path in result:
        parent = path.rpartition('/')[0]
        if parent and (parent not in result or result[parent]['kind'] != 'directory'):
            raise ValueError('附件清单缺少父目录')
    return name, kind, sorted(result.values(), key=lambda entry: entry['path']), total


def principal(source):
    return digest(['remote', source['sourceBinding'], source.get('sourceAccount')]
                  if source and source.get('sourceBinding') else ['local'])


def target_identity(bridge, value):
    if not isinstance(value, dict):
        raise ValueError('请选择附件所属会话或新建目标')
    if value.get('type') == 'thread' and set(value) == {'type', 'threadId'}:
        from carryon.sessions.catalog import valid_id
        thread_id = valid_id(value['threadId'])
        bridge.assert_target(thread_id)
        return {'type': 'thread', 'threadId': thread_id}
    if value.get('type') == 'creation' and not set(value) - {'type', 'projectId'}:
        project_id = value.get('projectId')
        if getattr(bridge.catalog, 'independent', False):
            from carryon.workspaces.workspace import project_identity
            if project_id not in (None, project_identity(None)[0]):
                raise BridgeError('此工作区不支持该新建项目', 409)
            return {'type': 'creation', 'projectId': None}
        from carryon.sessions.creation import resolve_target
        project = resolve_target(bridge.catalog, project_id)
        if project is None:
            return {'type': 'creation', 'projectId': None}
        return {'type': 'creation', 'projectId': project_id, 'project': project}
    raise ValueError('附件目标无效')


def _directory(parent, name, create=False):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    return os.open(name, DIRECTORY, dir_fd=parent)


@contextmanager
def _child(parent, name, create=False):
    fd = _directory(parent, name, create)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _parent(content, path):
    current = os.dup(content)
    try:
        for part in path.split('/')[:-1]:
            next_fd = _directory(current, part)
            os.close(current)
            current = next_fd
        yield current, path.split('/')[-1]
    finally:
        os.close(current)


@contextmanager
def _file(content, path, writable=False, create=False):
    with _parent(content, path) as (parent, name):
        flags = (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(name, flags, 0o600, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BridgeError('附件不是独立普通文件', 409)
        yield fd
    finally:
        os.close(fd)


def _read_record(batch):
    with _file(batch, 'record.json') as fd:
        if os.fstat(fd).st_size > 100000:
            raise BridgeError('附件记录损坏', 409)
        return json.loads(os.read(fd, 100001))


def _save_record(batch, record):
    name = '.record-' + uuid.uuid4().hex
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True).encode()
    try:
        with _file(batch, name, writable=True, create=True) as fd:
            _write(fd, payload)
            os.fsync(fd)
        os.replace(name, 'record.json', src_dir_fd=batch, dst_dir_fd=batch)
        os.fsync(batch)
    finally:
        try:
            os.unlink(name, dir_fd=batch)
        except FileNotFoundError:
            pass


def _write(fd, data):
    while data:
        written = os.write(fd, data)
        if written <= 0:
            raise OSError('附件写入中断')
        data = data[written:]


class Uploads:
    def __init__(self, bridge, source=None, authorize=None):
        self.bridge, self.owner, self.authorize = bridge, principal(source), authorize
        if not hasattr(bridge, 'workspace_directory'):
            raise BridgeError('当前服务尚未启用附件上传', 503)
        self.directory = Path(bridge.workspace_directory) / 'attachments'

    def check(self, record=None):
        self.bridge.require()
        if self.authorize:
            self.authorize()
        if record is not None:
            if record['owner'] != self.owner:
                raise BridgeError('附件不存在', 404)
            expected = {k: v for k, v in record['target'].items() if k != 'project'}
            if target_identity(self.bridge, expected) != record['target']:
                raise BridgeError('附件目标已改变，请重新上传', 409)

    @contextmanager
    def locked(self):
        self.check()
        try:
            with _child(None, str(self.directory.parent)) as workspace:
                with _child(workspace, 'attachments', True) as root:
                    try:
                        lock = os.open('.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
                    except FileExistsError:
                        lock = os.open('.lock', os.O_RDWR | os.O_NOFOLLOW, dir_fd=root)
                    try:
                        if not stat.S_ISREG(os.fstat(lock).st_mode) or os.fstat(lock).st_nlink != 1:
                            raise BridgeError('附件存储不可用', 409)
                        fcntl.flock(lock, fcntl.LOCK_EX)
                        self.check()
                        yield root
                    finally:
                        os.close(lock)
        except OSError as exc:
            raise BridgeError('附件存储不可用或文件已改变', 409) from exc

    @contextmanager
    def batch(self, root, identifier):
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise ValueError('附件 ID 无效')
        try:
            with _child(root, identifier) as batch:
                record = _read_record(batch)
                self.check(record)
                yield batch, record
        except FileNotFoundError:
            raise BridgeError('附件不存在', 404) from None

    def receipt(self, record):
        result = {key: record[key] for key in ('id', 'name', 'kind', 'state')}
        result['target'] = {k: v for k, v in record['target'].items() if k != 'project'}
        if record['state'] == 'complete':
            result['path'] = str(self.directory / record['id'] / 'content' / record['name'])
        return result

    def begin(self, data):
        fields(data, {'requestId', 'name', 'kind', 'entries', 'target'})
        validate_request_id(data.get('requestId'))
        name, kind, entries, total = manifest(data)
        target = target_identity(self.bridge, data.get('target'))
        identity = digest([self.owner, data['requestId']])
        fingerprint = digest([name, kind, entries, target])
        with self.locked() as root:
            stored = 0
            for identifier in os.listdir(root):
                if not IDENTIFIER.fullmatch(identifier):
                    continue
                with _child(root, identifier) as batch:
                    record = _read_record(batch)
                    stored += record['reservedBytes']
                    if record['requestKey'] == identity:
                        self.check(record)
                        if record['fingerprint'] != fingerprint:
                            raise BridgeError('requestId 已用于不同附件', 409)
                        if record['state'] == 'preparing':
                            self.prepare(batch, record)
                        return self.receipt(record)
            reserved = total + len(json.dumps(entries, ensure_ascii=False).encode()) + 4096
            if stored + reserved > MAX_STORAGE_BYTES:
                raise BridgeError('附件存储已达 1 GiB 上限，请在电脑管理已上传附件', 409)
            record = {'id': uuid.uuid4().hex, 'owner': self.owner, 'requestKey': identity,
                      'fingerprint': fingerprint, 'name': name, 'kind': kind, 'entries': entries,
                      'target': target, 'reservedBytes': reserved, 'state': 'preparing'}
            pending = '.pending-' + record['id']
            os.mkdir(pending, 0o700, dir_fd=root)
            try:
                with _child(root, pending) as batch:
                    _save_record(batch, record)
                    self.check(record)
                # Every published ID has a durable record. A crash or revoked
                # authorization before publication cannot poison later scans.
                os.rename(pending, record['id'], src_dir_fd=root, dst_dir_fd=root)
                os.fsync(root)
            finally:
                try:
                    with _child(root, pending) as batch:
                        try:
                            os.unlink('record.json', dir_fd=batch)
                        except FileNotFoundError:
                            pass
                    os.rmdir(pending, dir_fd=root)
                except OSError:
                    pass
            with _child(root, record['id']) as batch:
                self.prepare(batch, record)
            return self.receipt(record)

    def prepare(self, batch, record):
        with _child(batch, 'content', True) as content:
            for entry in record['entries']:
                with _parent(content, entry['path']) as (parent, name):
                    if entry['kind'] == 'directory':
                        with _child(parent, name, True):
                            pass
                    else:
                        try:
                            with _file(content, entry['path'], writable=True, create=True):
                                pass
                        except FileExistsError:
                            with _file(content, entry['path']) as fd:
                                if os.fstat(fd).st_size:
                                    raise BridgeError('附件初始化状态不一致', 409)
            os.fsync(content)
        record['state'] = 'uploading'
        _save_record(batch, record)

    def chunk(self, data):
        fields(data, {'uploadId', 'path', 'offset', 'data'})
        path = relative_path(data.get('path'))
        offset, encoded = data.get('offset'), data.get('data')
        if (type(offset) is not int or offset < 0 or not isinstance(encoded, str)
                or not 0 < len(encoded) <= LIMITS['chunkBytes'] * 4 // 3):
            raise ValueError('上传分块无效')
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('上传分块编码无效') from None
        if not 0 < len(payload) <= LIMITS['chunkBytes']:
            raise ValueError('上传分块过大或为空')
        with self.locked() as root, self.batch(root, data.get('uploadId')) as (batch, record):
            entry = next((entry for entry in record['entries'] if entry['path'] == path), None)
            if entry is None or entry['kind'] != 'file' or offset + len(payload) > entry['size']:
                raise ValueError('上传分块超出文件范围')
            with _child(batch, 'content') as content:
                with _file(content, path) as fd:
                    info = os.fstat(fd)
                    size = info.st_size
                    if size > entry['size'] or offset > size:
                        raise BridgeError('上传偏移或文件大小已改变', 409)
                    overlap = min(len(payload), size - offset)
                    os.lseek(fd, offset, os.SEEK_SET)
                    if os.read(fd, overlap) != payload[:overlap]:
                        raise BridgeError('同一偏移的上传内容不同', 409)
                    if overlap == len(payload):
                        return {'offset': offset + len(payload)}
                if record['state'] != 'uploading':
                    raise BridgeError('附件已封存', 409)
                self.check(record)
                with _file(content, path, writable=True) as fd:
                    current = os.fstat(fd)
                    if (current.st_dev, current.st_ino, current.st_size) != (info.st_dev, info.st_ino, size):
                        raise BridgeError('上传文件已改变', 409)
                    os.lseek(fd, size, os.SEEK_SET)
                    _write(fd, payload[overlap:])
                    os.fsync(fd)
                return {'offset': offset + len(payload)}

    def verify(self, batch, record, seal=False):
        with _child(batch, 'content') as content:
            expected = {entry['path']: entry for entry in record['entries']}
            observed = set()
            def visit(directory, prefix=''):
                for name in os.listdir(directory):
                    path = prefix + name
                    entry = expected.get(path)
                    if entry is None:
                        raise BridgeError('附件包含清单之外的内容', 409)
                    observed.add(path)
                    if entry['kind'] == 'directory':
                        with _child(directory, name) as child:
                            visit(child, path + '/')
                    else:
                        with _file(directory, name) as fd:
                            if os.fstat(fd).st_size != entry['size']:
                                raise BridgeError('附件尚未上传完整', 409)
                            checksum = hashlib.sha256()
                            remaining = entry['size']
                            while remaining and (block := os.read(fd, min(LIMITS['chunkBytes'], remaining))):
                                checksum.update(block)
                                remaining -= len(block)
                            if remaining or os.read(fd, 1) or checksum.hexdigest() != entry['sha256']:
                                raise BridgeError('附件内容校验失败', 409)
            visit(content)
            if observed != set(expected):
                raise BridgeError('附件内容不完整', 409)
            if seal:
                # Verify the entire batch before sealing any member: an incomplete
                # sibling must not make an otherwise resumable file unwritable.
                for entry in sorted(record['entries'], key=lambda item: item['path'].count('/'), reverse=True):
                    if entry['kind'] == 'file':
                        with _file(content, entry['path']) as fd:
                            os.fchmod(fd, 0o400)
                    else:
                        with _parent(content, entry['path']) as (parent, name), _child(parent, name) as child:
                            os.fchmod(child, 0o500)
                os.fchmod(content, 0o500)

    def complete(self, data):
        fields(data, {'uploadId'})
        with self.locked() as root, self.batch(root, data.get('uploadId')) as (batch, record):
            if record['state'] not in ('uploading', 'complete'):
                raise BridgeError('附件尚未初始化完成', 409)
            self.verify(batch, record, seal=True)
            self.check(record)
            record['state'] = 'complete'
            _save_record(batch, record)
            return self.receipt(record)

    def read(self, identifier):
        with self.locked() as root, self.batch(root, identifier) as (batch, record):
            if record['state'] == 'complete':
                self.verify(batch, record)
            result = self.receipt(record)
            with _child(batch, 'content') as content:
                result['entries'] = []
                for entry in record['entries']:
                    if entry['kind'] == 'file':
                        with _file(content, entry['path']) as fd:
                            entry = {**entry, 'offset': os.fstat(fd).st_size}
                    result['entries'].append(entry)
            return result

    def project(self, data, target):
        identifiers = data.get('uploads')
        if (not isinstance(identifiers, list) or len(identifiers) > 20
                or any(not isinstance(value, str) for value in identifiers)
                or len(set(identifiers)) != len(identifiers)):
            raise ValueError('最多引用 20 个不同附件')
        prompt = text(data.get('prompt'), allow_empty=True)
        expected = target_identity(self.bridge, target)
        references = []
        with self.locked() as root:
            for identifier in identifiers:
                with self.batch(root, identifier) as (batch, record):
                    if record['state'] != 'complete' or record['target'] != expected:
                        raise BridgeError('附件未完成或不属于此目标', 409)
                    self.verify(batch, record)
                    receipt = self.receipt(record)
                    references.append({'name': receipt['name'], 'path': receipt['path']})
            self.check()
        from carryon.sessions.file_references import project
        projected = project(prompt, references)
        text(projected, allow_empty=True)
        return {key: value for key, value in {**data, 'prompt': projected}.items() if key != 'uploads'}


def project_request(bridge, path, data, source, authorize):
    if 'uploads' not in data:
        return data
    if path == '/api/threads':
        target = {'type': 'creation', 'projectId': data.get('projectId')}
    elif re.fullmatch(r'/api/threads/[^/]+/(compose|messages|operations)', path):
        if path.endswith('/operations') and data.get('action') not in ('steer', 'queue-add'):
            raise ValueError('此操作不支持上传附件')
        target = {'type': 'thread', 'threadId': path.split('/')[3]}
    else:
        raise ValueError('此接口不支持上传附件')
    return Uploads(bridge, source, authorize).project(data, target)
