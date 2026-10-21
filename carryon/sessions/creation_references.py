"""Discover references in the authoritative destination before a thread exists."""
from pathlib import Path
from tempfile import TemporaryDirectory
from carryon.errors import BridgeError
from carryon.errors import IPCError
from carryon.paths import private_dir
from carryon.workspaces.workspace import project_identity
from carryon.sessions import skills, mentions


def discover(bridge, project_id=None, authorize=None):
    ipc, generation = bridge.require()
    independent = getattr(bridge.catalog, 'independent', False)
    if independent:
        if project_id not in (None, project_identity(None)[0]): raise BridgeError('此工作区不支持所选项目', 409)
        cwd = str(private_dir(bridge.workspace_directory / 'tasks'))
        project = None
    else:
        from carryon.sessions.creation import resolve_project, resolve_target
        project = resolve_target(bridge.catalog, project_id)
        cwd = project['cwd'] if project else str(private_dir(bridge.owners().directory / 'tasks'))
    def check():
        with bridge.lock:
            bridge.check_generation(ipc, generation)
            if authorize: authorize()
            if project is not None and resolve_project(bridge.catalog, project_id) != project:
                raise BridgeError('目标项目已改变，请重新选择项目')
    def read(runtime):
        check(); runtime.require_account()
        identity = runtime.connection_identity
        if not runtime.connected: raise IPCError('原生连接已断开')
        skill_rows = skills.catalog(runtime, cwd)
        skill_rows = {**skill_rows, 'skills': skills.skill_icons(skill_rows['skills'])}
        mention_rows = mentions.catalog(runtime, cwd)
        check()
        if not runtime.connected or runtime.connection_identity != identity:
            raise IPCError('引用目录所属原生连接已改变')
        return {'cwd': cwd, 'skills': skill_rows['skills'], 'mentions': mention_rows['mentions'],
                'errors': skill_rows['errors'] + mention_rows['errors']}
    if independent:
        # Match the empty child directory used by app_creation. Repo-local plugin
        # inventories at tasks/ itself do not necessarily apply to its children.
        with TemporaryDirectory(prefix='reference-discovery-', dir=cwd) as directory:
            cwd = directory
            return read(ipc)
    service = bridge.owners()
    with TemporaryDirectory(prefix='reference-discovery-', dir=private_dir(service.directory)) as directory:
        runtime = service.runtime_factory(bridge.catalog.home, runtime_directory=Path(directory))
        try:
            runtime.connect()
            if project is None:
                with TemporaryDirectory(prefix='reference-discovery-', dir=cwd) as task_directory:
                    cwd = task_directory
                    return read(runtime)
            return read(runtime)
        finally: runtime.close()
