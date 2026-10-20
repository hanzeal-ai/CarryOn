"""Project-scoped native file discovery and ordinary-text reference projection."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from carryon.codex_protocol.read_control import reader
from carryon.errors import IPCError
from carryon.sessions.native_metadata import configuration_cwd
from carryon.sessions.user_messages import HEADER, SEPARATOR, REQUEST_HEADER


def clean(value, maximum):
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(ord(c) < 32 or ord(c) == 127 or c in '\u2028\u2029' for c in value)


def query(value):
    if not clean(value, 200) or not value.strip() or value != value.strip():
        raise ValueError('文件搜索条件无效')
    return value


def selections(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError('最多引用 20 个项目文件')
    result, paths = [], set()
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'name', 'path', 'query'}
                or not clean(item['name'], 200) or not clean(item['path'], 4096)
                or not Path(item['path']).is_absolute() or Path(item['path']).name != item['name']):
            raise ValueError('项目文件引用无效')
        query(item['query'])
        if item['path'] in paths:
            raise ValueError('项目文件引用重复')
        paths.add(item['path'])
        result.append(dict(item))
    return result


def project(prompt, files):
    if not files:
        return prompt
    from carryon.sessions.user_messages import _unwrap_attachments
    references = list(files)
    # Uploaded references have already been resolved by the HTTP route. Preserve
    # one native display envelope when project references are added at delivery.
    while True:
        request, paths = _unwrap_attachments(prompt)
        if request == prompt:
            break
        references.extend({'name': Path(path).name, 'path': path} for path in paths)
        prompt = request
    unique = {item['path']: item for item in references}
    return '\n' + HEADER + '\n' + ''.join('\n## ' + item['name'] + ': ' + item['path'] + '\n' for item in unique.values()) + '\n' + SEPARATOR + '\n\n' + REQUEST_HEADER + prompt


def project_root(cwd):
    try:
        root = Path(cwd).resolve(strict=True)
        if not root.is_dir():
            raise IPCError('项目目录不可用')
        return str(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise IPCError('项目目录不可用') from exc


def contained(cwd, path):
    """Reject escaped symlinks and missing files without reading their contents."""
    try:
        root = Path(cwd).resolve(strict=True)
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise IPCError('文件已移除或不属于当前项目')
    except (OSError, ValueError, RuntimeError) as exc:
        raise IPCError('文件已移除或不属于当前项目') from exc


def inventory(runtime, cwd, term, verify):
    term = query(term)
    result = runtime.rpc('fuzzyFileSearch', {'query': term, 'roots': [cwd]})
    verify()
    if not isinstance(result, dict) or not isinstance(result.get('files'), list):
        raise IPCError('原生文件搜索回执无效')
    rows, paths = [], set()
    for hit in result['files']:
        if not isinstance(hit, dict) or hit.get('root') != cwd or hit.get('match_type') not in ('file', 'directory'):
            raise IPCError('原生文件搜索范围无效')
        relative, name = hit.get('path'), hit.get('file_name')
        if (not clean(relative, 4096) or PurePosixPath(relative).is_absolute()
                or any(part in ('.', '..') for part in relative.split('/'))
                or not clean(name, 200) or PurePosixPath(relative).name != name):
            raise IPCError('原生文件搜索路径无效')
        if hit['match_type'] == 'directory':
            continue
        path = str(Path(cwd) / relative)
        try:
            contained(cwd, path)
        except IPCError:
            continue
        if path in paths:
            raise IPCError('原生文件搜索身份重复')
        paths.add(path)
        rows.append({'name': name, 'path': path, 'relativePath': relative, 'query': term})
    return rows


def read(bridge, tid, term, authorize=None):
    term = query(term)
    ipc, generation = bridge.require()
    bridge.assert_target(tid)
    source_cwd = configuration_cwd(bridge, tid)
    cwd = project_root(source_cwd)
    def check():
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if authorize:
                authorize()
            if configuration_cwd(bridge, tid) != source_cwd or project_root(source_cwd) != cwd:
                raise IPCError('文件所属项目已改变')
    with reader(bridge) as (runtime, verify):
        check()
        rows = inventory(runtime, cwd, term, verify)
        check()
        return {'threadId': tid, 'cwd': cwd, 'files': rows}


def guard(runtime, tid, files, before_send):
    from carryon.sessions.skills import verify
    files = selections(files)
    if not files:
        return before_send
    state = runtime.current(tid)
    if not state or state.get('_metadataOnly') or not runtime.connected:
        raise IPCError('项目文件引用需要已连接的原生会话')
    cwd = state.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise IPCError('项目工作目录无效')
    identity = (runtime.connection_identity, cwd)
    source_cwd = cwd
    cwd = project_root(source_cwd)
    def current():
        verify(runtime, tid, identity)
        if project_root(source_cwd) != cwd:
            raise IPCError('文件所属项目已改变')
    candidates = {}
    for term in dict.fromkeys(item['query'] for item in files):
        candidates[term] = {(row['name'], row['path']) for row in inventory(runtime, cwd, term, current)}
    if any((item['name'], item['path']) not in candidates[item['query']] for item in files):
        raise IPCError('项目文件引用已改变，请重新搜索')
    def guarded(write):
        def checked():
            with runtime.lock:
                current()
                for item in files:
                    contained(cwd, item['path'])
                write()
        if before_send:
            before_send(checked)
        else:
            checked()
    return guarded


@contextmanager
def delivery_session(bridge, tid, ipc, authorize, *, starts_turn=False):
    """Use the owned runtime's transaction boundary, never a delayed socket guard."""
    if getattr(ipc, 'protocol', None) == 'codex-app-server':
        yield ipc, lambda write: write()
    elif hasattr(bridge, 'native_session'):
        with bridge.native_session(tid, authorize, loaded_only=True,
                                   track_future_turns=starts_turn) as target:
            if target is None:
                raise IPCError('项目文件引用需要已加载的原生会话')
            yield target
    else:
        raise IPCError('当前会话不支持项目文件引用')
