"""Sidebar status is a projection of native runtime, never inferred from recency."""


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
