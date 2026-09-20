import Foundation

/// Display semantics only. Native runtime and request records remain authoritative.
public struct ConversationState: Equatable, Sendable {
    public enum Tone: String, Sendable { case active, waiting, success, failure, neutral }
    public let label: String
    public let symbol: String
    public let tone: Tone
    public init(_ label: String, _ symbol: String, _ tone: Tone = .neutral) {
        self.label = label; self.symbol = symbol; self.tone = tone
    }
    public static func session(_ history: JSONValue, connected: Bool, readFailed: Bool = false) -> Self {
        if readFailed { return .init("读取失败 · 状态未知", "exclamationmark.circle", .failure) }
        guard connected else { return .init("状态待确认", "questionmark.circle") }
        if history["syncing"].bool == true { return .init("正在同步", "arrow.triangle.2.circlepath", .active) }
        let runtime = history["status"]["state"].text
        if history["source"].text == "local-rollout" && history["syncing"].bool == false {
            return .init(runtime == "notLoaded" ? "尚未加载" : "状态未知", "clock")
        }
        if runtime == "error" { return .init("运行异常", "exclamationmark.circle", .failure) }
        if runtime == "notLoaded" { return .init("尚未加载", "clock") }
        guard ["idle", "running", "waiting"].contains(runtime) else { return .init("状态未知", "questionmark.circle") }
        let requests = history["controls"]["requests"].array
        if requests.contains(where: { ["command-approval", "file-approval", "permissions-approval"].contains($0["action"].text) }) {
            return .init("等待批准", "hand.raised", .waiting)
        }
        if !requests.isEmpty || runtime == "waiting" { return .init("等待你的回应", "questionmark.bubble", .waiting) }
        if runtime == "running" { return .init("执行中", "circle.dotted", .active) }
        if !history["queue"]["messages"].array.isEmpty {
            let paused = history["queue"]["messages"].array.contains { $0["pausedReason"] != .null }
            return .init(paused ? "队列已暂停" : "等待执行", "text.badge.clock", .waiting)
        }
        let last = history["controls"]["lastTurnStatus"].string ?? history["timeline"].array.last(where: { $0["type"].text == "turn" })?["status"].text ?? ""
        return status(last, fallback: "就绪")
    }
    public static func status(_ value: String, fallback: String = "状态未知") -> Self {
        switch value {
        case "inProgress", "running", "started", "active": .init("执行中", "circle.dotted", .active)
        case "waiting", "pending", "requiresApproval": .init("等待处理", "clock", .waiting)
        case "completed", "done", "succeeded", "success": .init("已完成", "checkmark.circle", .success)
        case "failed", "error", "denied", "rejected": .init("失败", "exclamationmark.circle", .failure)
        case "interrupted", "cancelled", "canceled", "stopped": .init("已中断", "stop.circle")
        case "updated", "interacted": .init("有更新", "bubble.left")
        default: .init(fallback, "circle")
        }
    }
    public static func activity(_ item: JSONValue) -> Self {
        let data = item["data"]
        if item["type"].text == "error" { return status("failed") }
        if data["error"] != .null && data["error"] != .string("") { return status("failed") }
        if item["status"].text == "inProgress" { return status("inProgress") }
        if ["interrupted", "cancelled", "canceled"].contains(item["status"].text) { return status(item["status"].text) }
        if data["success"].bool == false || (data["exitCode"].int.map { $0 != 0 } ?? false) { return status("failed") }
        if item["type"].text == "subAgentActivity" { return status(data["kind"].text) }
        return status(item["status"].text)
    }
}

/// Immutable destination captured when an action sheet opens. Never redirects to a new selection.
public struct ConversationActionTarget: Equatable, Sendable {
    public let scope: String
    public let threadID: String
    public let parentID: String?
    public let isActivity: Bool
    public init(scope: String, threadID: String, parentID: String? = nil, isActivity: Bool = false) {
        self.scope = scope; self.threadID = threadID; self.parentID = parentID; self.isActivity = isActivity
    }
    public func matches(scope: String, selectedThreadID: String?, sideThreadID: String?, snapshot: JSONValue) -> Bool {
        guard self.scope == scope, snapshot["thread"]["id"].text == threadID else { return false }
        if let parentID { return selectedThreadID == parentID && sideThreadID == threadID && snapshot["parentId"].text == parentID }
        return selectedThreadID == threadID
    }
    public func path(_ endpoint: String) -> String {
        "/api/\(parentID == nil ? "threads" : "side-chats")/\(ConsoleAddress.component(threadID))/\(endpoint)"
    }
    public func body(_ fields: [String: JSONValue]) -> JSONValue {
        var result = fields
        if let parentID { result["parentId"] = .string(parentID) }
        return .object(result)
    }
}
