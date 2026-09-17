import Foundation

/// A view of the latest native turn and its outstanding requests, never execution narration.
public struct ActivityDetail: Sendable {
    public enum Kind: Equatable, Sendable { case completed, approval, question, failed, other }
    public let kind: Kind
    public let result: JSONValue
    public let requests: [JSONValue]
    public let questions: [JSONValue]
    public let failure: String?
    public let completedAt: Double?
    public let anchorID: String?

    public init(history: JSONValue) {
        let timeline = history["timeline"].array
        let turn = timeline.last { $0["type"].text == "turn" } ?? .null
        let items = timeline.filter { $0["turnId"] == turn["turnId"] && $0["type"].text != "turn" }
        requests = history["controls"]["requests"].array
        let questionItems = timeline.filter { item in
            item["asyncQuestions"].array.contains { $0["active"].bool == true && $0["answer"] == .null }
        }
        questions = questionItems.flatMap { $0["asyncQuestions"].array }.filter { $0["active"].bool == true && $0["answer"] == .null }
        result = items.last { $0["type"].text == "agentMessage" && $0["data"]["delivery"].text != "async" && !["analysis", "commentary"].contains($0["phase"].text) } ?? .null
        if case .number(let time) = turn["data"]["completedAt"] { completedAt = time } else { completedAt = nil }
        let failed = turn["status"].text == "failed" || history["status"]["state"].text == "error"
        let errorItem = items.last { $0["type"].text == "error" }
        if failed {
            failure = Self.errorText(turn["data"]["error"]) ?? errorItem.flatMap { Self.errorText($0["data"]["error"]) ?? Self.errorText($0["text"]) }
                ?? Self.errorText(history["status"]["error"]) ?? "会话未提供具体失败原因"
        } else { failure = nil }
        if requests.contains(where: { ["command-approval", "file-approval", "permissions-approval"].contains($0["action"].text) }) { kind = .approval }
        else if !requests.isEmpty || !questions.isEmpty { kind = .question }
        else if failed { kind = .failed }
        else if turn["status"].text == "completed" { kind = .completed }
        else { kind = .other }
        if let request = requests.first {
            let itemID = request["params"]["itemId"]
            let row = itemID == .null ? nil : timeline.first { $0["nativeId"] == itemID }
            anchorID = row.flatMap { original in
                ConversationProcess.timeline(timeline).first { $0["id"] == original["id"] || $0["items"].array.contains { $0["id"] == original["id"] } }?["id"].string
            } ?? Self.visibleAnchor(turnID: request["params"]["turnId"] == .null ? turn["turnId"] : request["params"]["turnId"], timeline: timeline)
        }
        else if let item = questionItems.first { anchorID = item["id"].string }
        else if failed { anchorID = errorItem?["id"].string ?? Self.visibleAnchor(turnID: turn["turnId"], timeline: timeline) }
        else { anchorID = result["id"].string ?? Self.visibleAnchor(turnID: turn["turnId"], timeline: timeline) }
    }

    public var label: String {
        switch kind {
        case .completed: "任务完成"
        case .approval: "任务需要审核"
        case .question: "需要回答问题"
        case .failed: "执行失败"
        case .other: "会话更新"
        }
    }
    private static func errorText(_ value: JSONValue) -> String? {
        if let text = value.string, !text.isEmpty { return text }
        if let text = value["message"].string, !text.isEmpty { return text }
        if value.object != nil || !value.array.isEmpty { return value.formatted }
        return nil
    }
    private static func visibleAnchor(turnID: JSONValue, timeline: [JSONValue]) -> String? {
        ConversationProcess.timeline(timeline).last { $0["turnId"] == turnID }?["id"].string
    }
}
