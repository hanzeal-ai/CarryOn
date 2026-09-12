"""Validate the pinned native schemas; no third-party runtime dependency."""
import hashlib
import json
from pathlib import Path

SCHEMAS = json.loads(Path(__file__).with_name('native_contracts.json').read_text())


def validate(value, schema, root=None, path='value'):
    root = root or schema
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith('#/definitions/'):
            raise ValueError('Unsupported schema reference')
        return validate(value, root['definitions'][ref.split('/')[-1]], root, path)
    for key in ('anyOf', 'oneOf'):
        if key in schema:
            matched = 0
            for branch in schema[key]:
                try:
                    validate(value, branch, root, path)
                    matched += 1
                except ValueError:
                    pass
            if not matched or key == 'oneOf' and matched != 1:
                raise ValueError(path + ' 不符合原生协议允许的类型或选项')
    for branch in schema.get('allOf', []):
        validate(value, branch, root, path)
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    actual = ('null' if value is None else 'boolean' if type(value) is bool else
              'integer' if type(value) is int else 'number' if type(value) is float else
              'string' if isinstance(value, str) else 'array' if isinstance(value, list) else
              'object' if isinstance(value, dict) else 'invalid')
    if types and actual not in types and not (actual == 'integer' and 'number' in types):
        raise ValueError(path + ' 类型不正确')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ' 不在允许的选项中')
    if isinstance(value, str) and len(value) < schema.get('minLength', 0):
        raise ValueError(path + ' 不能为空')
    if type(value) in (float, int) and value < schema.get('minimum', float('-inf')):
        raise ValueError(path + ' 小于允许值')
    if isinstance(value, dict):
        if set(schema.get('required', [])) - set(value):
            raise ValueError(path + ' 缺少必要字段')
        properties = schema.get('properties')
        if properties is not None:
            # Unknown fields are rejected instead of silently ignored by native code.
            if set(value) - set(properties):
                raise ValueError(path + ' 包含未识别字段: ' + ', '.join(set(value) - set(properties)))
            for key, item in value.items():
                validate(item, properties[key], root, path + '.' + key)
    if isinstance(value, list) and 'items' in schema:
        for index, item in enumerate(value):
            validate(item, schema['items'], root, path + '[' + str(index) + ']')


def settings(value, thread_id):
    if not isinstance(value, dict) or not value or 'threadId' in value:
        raise ValueError('settings 必须为非空对象，不包含 threadId')
    validate({'threadId': thread_id, **value}, SCHEMAS['settings'])
    if value.get('permissions') is not None and value.get('sandboxPolicy') is not None:
        raise ValueError('permissions 不能与 sandboxPolicy 同时设置')
    if value.get('activePermissionProfile') is not None and value.get('sandboxPolicy') is not None:
        raise ValueError('activePermissionProfile 不能与 sandboxPolicy 同时设置')
    if value.get('activePermissionProfile') is not None and value.get('permissions') is not None:
        if value['activePermissionProfile']['id'] != value['permissions']:
            raise ValueError('权限配置 ID 不一致')
    if value.get('cwd') is not None and not Path(value['cwd']).is_absolute():
        raise ValueError('cwd 必须为绝对路径')
    return value


def approval_choices(action, params):
    if action not in ('command-approval', 'file-approval'):
        return []
    native = params.get('availableDecisions')
    if native is not None:
        return native
    choices = ['accept', 'acceptForSession', 'decline', 'cancel']
    if action == 'command-approval':
        amendment = params.get('proposedExecpolicyAmendment')
        if amendment:
            choices.append({'acceptWithExecpolicyAmendment': {'execpolicy_amendment': amendment}})
        for amendment in params.get('proposedNetworkPolicyAmendments') or []:
            choices.append({'applyNetworkPolicyAmendment': {'network_policy_amendment': amendment}})
    return choices


def approval(action, decision, params):
    schema = SCHEMAS['command' if action == 'command-approval' else 'file']
    validate({'decision': decision}, schema)
    if decision not in approval_choices(action, params):
        raise ValueError('该请求未提供此审批决定或授权范围')
    return decision


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise ValueError('请输入 1–16000 字符的内容')
    return value.strip()
