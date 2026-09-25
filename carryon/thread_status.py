"""Sidebar status is a projection of native runtime, never inferred from recency."""

from .errors import BridgeError


def project_status(state):
    if not isinstance(state, dict) or not state:
        return {"state": "unknown", "label": "状态未知"}
    runtime = state.get("threadRuntimeStatus") or {}
    if not isinstance(runtime, dict):
        return {"state": "unknown", "label": "状态未知"}
    kind = runtime.get("type")
    flags = runtime.get("activeFlags") or []
    if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
        return {"state": "unknown", "label": "状态未知"}
    if kind == "notLoaded":
        code, label = "notLoaded", "未加载"
    elif kind == "systemError":
        code, label = "error", "运行异常"
    elif state.get("requests") or any(f in ("waitingOnApproval", "waitingOnUserInput") for f in flags):
        code, label = "waiting", "待处理"
    elif kind == "active":
        code, label = "running", "执行中"
    elif kind == "idle":
        code, label = "idle", "空闲"
    else:
        code, label = "unknown", "状态未知"
    return {"state": code, "label": label}

def idle_snapshot(state):
    status = project_status(state)['state']
    if status == 'waiting':
        raise BridgeError("会话有待处理的审批或输入，请先在 Codex App 处理")
    if status != 'idle':
        raise BridgeError("会话不是已确认的空闲状态，请等待任务结束或在 Codex App 查看")
