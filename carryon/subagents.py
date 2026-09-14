"""Native subagent topology and access policy, shared by every transport/client."""
import json
from .catalog import ID
from .operations import turns
from .errors import BridgeError


def agent_name(path):
    name = (path if isinstance(path, str) else '').rsplit('/', 1)[-1].replace('_', ' ')
    return name[:1].upper() + name[1:]


def spawn_source(row):
    source = row.get('source')
    try:
        source = json.loads(source) if isinstance(source, str) else source
    except ValueError:
        source = None
    subagent = source.get('subagent') if isinstance(source, dict) else None
    spawn = subagent.get('thread_spawn') if isinstance(subagent, dict) else None
    return spawn if isinstance(spawn, dict) else {}


def is_subagent(row):
    return row.get('thread_source', row.get('threadSource')) in ('subagent', 'sub-agent') or bool(spawn_source(row))


def references(items):
    """IDs come only from native structured events, never model-written names."""
    result = {}
    for item in items:
        kind = item.get('type')
        if kind == 'subAgentActivity':
            tid = item.get('agentThreadId')
            if isinstance(tid, str) and ID.fullmatch(tid):
                name = agent_name(item.get('agentPath'))
                result[tid] = {'id': tid, 'title': name or tid, 'activity': item.get('kind')}
        elif kind == 'collabAgentToolCall':
            receivers = {r.get('threadId'): r.get('thread') or {} for r in item.get('receiverThreads', []) if isinstance(r, dict)}
            for tid in item.get('receiverThreadIds', []):
                if isinstance(tid, str) and ID.fullmatch(tid):
                    receiver = receivers.get(tid, {})
                    source = spawn_source(receiver)
                    result[tid] = {'id': tid, 'title': receiver.get('name') or receiver.get('agentNickname') or source.get('agent_nickname') or tid}
    return list(result.values())


class Subagents:
    def __init__(self, bridge):
        self.bridge = bridge

    def access(self, row):
        if not is_subagent(row):
            return {'isSubagent': False, 'canInteract': True}
        parent = spawn_source(row).get('parent_thread_id')
        allowed = False
        if isinstance(parent, str) and ID.fullmatch(parent):
            ipc = self.bridge.ipc
            state = ipc.current(parent) if ipc and hasattr(ipc, 'current') else None
            def spawned(state):
                return any(i.get('type') == 'collabAgentToolCall' and i.get('tool') == 'spawnAgent'
                           and i.get('senderThreadId') == parent and row['id'] in i.get('receiverThreadIds', [])
                           for turn in turns(state or {}) for i in turn.get('items', []))
            allowed = spawned(state)
            if not allowed:
                try:
                    allowed = row['id'] in self.bridge.catalog.spawned_children(parent)
                except (ValueError, OSError):
                    pass
            # The desktop grants interaction for spawnAgent, not background activity.
        return {'isSubagent': True, 'parentId': parent, 'canInteract': allowed}

    def assert_interactive(self, thread_id):
        if not self.access(self.bridge.catalog.get(thread_id))['canInteract']:
            raise BridgeError('此子会话为只读，不能执行交互操作', 403)

    def list(self, parent_id):
        self.bridge.catalog.get(parent_id)
        rows = self.bridge.catalog.children(parent_id)
        return {'threads': [self.describe(row) for row in rows]}

    def describe(self, row):
        source = spawn_source(row)
        name = agent_name(source.get('agent_path') or row.get('agent_path'))
        return {'id': row['id'], 'title': row.get('name') or name or row.get('agent_nickname') or row.get('title') or row['id'],
                'cwd': row.get('cwd', ''), 'access': self.access(row)}

    def decorate(self, history, row):
        result = dict(history)
        result['access'] = self.access(row)
        result['access']['nativeReady'] = history.get('source') == 'desktop-snapshot'
        if result['access']['isSubagent']:
            result['thread'] = {**result['thread'], **self.describe(row)}
        if not result['access']['canInteract']:
            result['controls'] = {}
            result.pop('queue', None)
        return result
