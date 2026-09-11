"""Public conversation projection. Never expose full turn params or raw reasoning."""
import json
import re


def text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def pick(value, keys):
    return {key: value[key] for key in keys.split() if key in value}


FIELDS = {
    "userMessage": "content",
    "steeringUserMessage": "input",
    "steered": "",
    "agentMessage": "text phase memoryCitation questions delivery",
    "reasoning": "summary",  # Same display source as desktop; exclude content/encryptedContent.
    "commandExecution": "command cwd commandActions status aggregatedOutput exitCode durationMs processId",
    "mcpToolCall": "server tool arguments status result error durationMs",
    "dynamicToolCall": "tool arguments status contentItems success error durationMs",
    "functionCallOutput": "name namespace output",
    "fileChange": "status changes",
    "contextCompaction": "completed source",
    "webSearch": "query action status",
    "plan": "text plan explanation",
    "todo-list": "plan explanation",
    "collabAgentToolCall": "tool status senderThreadId receiverThreadIds prompt model reasoningEffort agentsStates",
    "subAgentActivity": "status agentNickname agentRole threadId activity summary",
    "imageView": "path imageCount",
    "imageGeneration": "status result revisedPrompt",
    "userInput": "questions completed",
    "userInputResponse": "questionsAndAnswers",
    "permissionRequest": "reason permissions response completed",
    "mcpServerElicitation": "message requestedSchema response completed action",
    "automaticApprovalReview": "status decision rationale reason",
    "error": "message error",
    "modelChanged": "model previousModel",
    "modelRerouted": "fromModel toModel reason",
    "enteredReviewMode": "review",
    "exitedReviewMode": "review",
    "sleep": "durationMs status",
    "worktreeInit": "status path error",
}

LABELS = {
    "commandExecution": "执行命令", "mcpToolCall": "调用工具", "dynamicToolCall": "调用工具",
    "functionCallOutput": "工具输出", "reasoning": "思考摘要", "fileChange": "文件修改",
    "contextCompaction": "压缩上下文", "webSearch": "搜索网页", "plan": "计划",
    "todo-list": "任务计划", "collabAgentToolCall": "Agent 协作", "subAgentActivity": "Agent 活动",
    "imageView": "查看图片", "imageGeneration": "生成图片", "userInput": "等待输入",
    "userInputResponse": "输入回复", "permissionRequest": "权限请求",
    "mcpServerElicitation": "工具请求输入", "automaticApprovalReview": "审批检查",
    "error": "执行错误", "modelChanged": "模型变更", "modelRerouted": "模型切换",
    "enteredReviewMode": "进入审查", "exitedReviewMode": "审查结果", "sleep": "等待",
    "steered": "补充指令已接收",
    "worktreeInit": "准备工作目录", "steeringUserMessage": "补充任务",
}


def project_item(item, turn, index):
    kind = item.get("type", "unknown")
    data = pick(item, FIELDS.get(kind, "status completed"))
    # The reasoning item has no lifecycle field in this version. Only the last
    # native item of an active turn can be displayed as currently thinking.
    active = turn.get("status") == "inProgress"
    status = item.get("status")
    if kind in ("reasoning", "contextCompaction"):
        completed = item.get("completed", not (active and index == len(turn.get("items", [])) - 1))
        status = "completed" if completed or not active else "inProgress"
    body = ""
    if kind == "agentMessage":
        body = item.get("text", "")
    elif kind in ("userMessage", "steeringUserMessage"):
        body = "\n".join(c.get("text", "") for c in item.get("content", item.get("input", [])) if c.get("type") == "text")
    elif kind == "reasoning":
        summary = item.get("summary", [])
        body = summary if isinstance(summary, str) else "\n".join(
            s if isinstance(s, str) else s.get("text", "") for s in summary)
    elif kind == "commandExecution":
        body = item.get("command", "")
    elif kind in ("plan", "error"):
        body = item.get("text", item.get("message", ""))
    title = LABELS.get(kind, kind)
    if kind in ("mcpToolCall", "dynamicToolCall"):
        title += " · " + ".".join(str(item[k]) for k in ("server", "tool") if item.get(k))
    if kind == "contextCompaction":
        title = ("手动" if item.get("source") == "manual" else "自动") + "压缩上下文"
    return {"id": f"{turn.get('turnId')}:{item.get('id', index)}", "nativeId": item.get("id"),
        "turnId": turn.get("turnId"), "type": kind, "title": title, "status": status,
        "text": body, "phase": item.get("phase"), "durationMs": item.get("durationMs"),
        "data": data, "supported": kind in FIELDS}


def project_timeline(turns, state):
    entries, unsupported = [], set()
    for position, turn in enumerate(turns):
        tid = turn.get("turnId", str(position))
        meta = pick(turn, "status turnStartedAtMs durationMs error diff")
        meta.update(pick(turn.get("params", {}), "model effort"))
        entries.append({"id": f"{tid}:turn", "turnId": tid, "type": "turn", "title": f"第 {position + 1} 轮",
                        "status": turn.get("status"), "data": meta})
        items = turn.get("items", [])
        delegated_output = None
        if not any(i.get("type") == "userMessage" for i in items):
            inputs = turn.get("params", {}).get("input", [])
            output = (turn.get("params", {}).get("toolOutput") or {}).get("output")
            if not inputs and isinstance(output, str) and output.startswith("<codex_delegation>"):
                match = re.search(r"<input>\s*([\s\S]*?)\s*</input>", output)
                if match:
                    inputs = [{"type":"text", "text":match[1]}]
                    delegated_output = output
            if inputs:
                entries.append(project_item({"type": "userMessage", "id": "input", "content": inputs}, turn, -1))
        for index, item in enumerate(items):
            if delegated_output is not None and item.get("type") == "functionCallOutput" and item.get("output") == delegated_output:
                continue  # The initial delegated input is displayed once as a user message.
            if item.get("type") == "agentMessage" and item.get("phase") == "analysis":
                continue
            if item.get("type") == "hookPrompt":
                continue  # Injected runtime instructions are not conversation display content.
            entry = project_item(item, turn, index)
            entries.append(entry)
            if not entry["supported"]:
                unsupported.add(entry["type"])
        if turn.get("diff"):
            entries.append({"id":f"{tid}:diff", "turnId":tid, "type":"turnDiff", "title":"本轮修改汇总",
                            "data":{"diff":turn["diff"]}})
        if turn.get("error"):
            entries.append({"id":f"{tid}:error", "turnId":tid, "type":"error", "title":"本轮错误",
                            "status":"failed", "data":{"error":turn["error"]}})
    from .operations import controls
    return {"timeline": entries, "controls": controls(state), "runtime": state.get("threadRuntimeStatus", {"type":"unknown"}),
        "metadata": pick(state, "latestModel latestReasoningEffort latestTokenUsageInfo gitInfo"),
        "pendingRequests": [{"id": r.get("id", r.get("requestId")), "method": r.get("method", r.get("type", "等待处理"))}
                            for r in state.get("requests", []) if isinstance(r, dict)],
        "coverage": {"unsupportedTypes": sorted(unsupported), "reasoning":"display-summary-only",
                     "attachments":"references-only", "refresh":"websocket-events"}}
