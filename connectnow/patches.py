"""Apply desktop Immer JSON patches atomically to a snapshot projection."""
from copy import deepcopy


def apply_patches(state, patches):
    result = deepcopy(state)
    if not isinstance(patches, list):
        raise ValueError('Invalid patches')
    for patch in patches:
        op, path = patch['op'], patch['path']
        if op not in ('add', 'replace', 'remove') or not isinstance(path, list):
            raise ValueError('Unsupported patch')
        if not path:
            if op == 'remove':
                raise ValueError('Cannot remove root')
            result = deepcopy(patch['value'])
            continue
        parent = result
        for key in path[:-1]:
            parent = parent[key]
        key = path[-1]
        if isinstance(parent, list):
            if type(key) is not int or not 0 <= key <= len(parent):
                raise ValueError('Invalid array index')
            if op == 'add':
                parent.insert(key, deepcopy(patch['value']))
            elif op == 'remove':
                parent.pop(key)
            else:
                parent[key] = deepcopy(patch['value'])
        elif isinstance(parent, dict) and isinstance(key, str):
            if op != 'add' and key not in parent:
                raise ValueError('Missing patch target')
            if op == 'remove':
                del parent[key]
            else:
                parent[key] = deepcopy(patch['value'])
        else:
            raise ValueError('Invalid patch target')
    if not isinstance(result, dict):
        raise ValueError('Invalid snapshot root')
    return result
