"""Presentation grouping only; service IDs remain the execution/auth boundary."""
import uuid

BACKENDS = ('desktop-ipc', 'codex-cli', 'app-server')


def assign_workspaces(services):
    """Upgrade local registrations without changing credentials, homes or endpoints."""
    groups = {}
    rows = sorted(services.values(), key=lambda row: row.get('backend') != 'desktop-ipc')
    for row in rows:
        if row.get('removed'):
            continue
        backend = row.get('backend', 'desktop-ipc')
        key = ('codex', row.get('codexHome')) if backend in ('desktop-ipc', 'codex-cli') and row.get('codexHome') else ('service', row['directory'])
        groups.setdefault(key, []).append(row)
    assigned = set()
    for rows in groups.values():
        existing = next((row for row in rows if row.get('workspaceId')), None)
        identity = existing['workspaceId'] if existing else uuid.uuid4().hex
        if identity in assigned:
            identity = uuid.uuid4().hex
        assigned.add(identity)
        name = existing.get('workspaceName') if existing else None
        name = name or rows[0].get('name') or '工作区'
        for row in rows:
            row['workspaceId'], row['workspaceName'] = identity, name


def descriptor(entry):
    if not entry or not entry.get('workspaceId'):
        return None
    return validate({'id': entry['workspaceId'], 'name': entry['workspaceName'], 'backend': entry.get('backend', 'desktop-ipc')})


def validate(value):
    if not isinstance(value, dict) or set(value) != {'id', 'name', 'backend'}:
        raise ValueError('工作区连接信息无效')
    identity, name = value['id'], value['name']
    if not isinstance(identity, str) or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('工作区标识无效')
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or value['backend'] not in BACKENDS:
        raise ValueError('工作区连接信息无效')
    return dict(value)


def public_descriptor(record):
    """Namespace grouping by binding owner; never combine credentials or grants."""
    value = record.get('workspace')
    if value is None:
        return None
    value = validate(value)
    owner = record.get('ownerUserId')
    if not owner:
        return None
    return {**value, 'id': uuid.uuid5(uuid.NAMESPACE_URL, str(owner) + ':' + value['id']).hex}
