import Foundation

/// Presentation only: native turn boundaries and message phases own the grouping.
public enum ConversationProcess {
    public static func timeline(_ source: [JSONValue]) -> [JSONValue] {
        let items = ConversationPresentation.visibleReasoning(source)
        var result: [JSONValue] = [], segment: [JSONValue] = []
        var turn: JSONValue = .null
        var turnID: String?
        func flushSegment() {
            guard !segment.isEmpty else { return }
            var pending: [JSONValue] = []
            func flush() {
                guard let first = pending.first else { return }
                result.append(.object(["id": .string((first["id"].string ?? first.formatted) + ":process"),
                    "type": .string("processGroup"), "turnId": first["turnId"], "status": turn["status"],
                    "active": .bool(turn["status"].text == "inProgress" && pending.last == segment.last),
                    "data": turn["data"], "items": .array(pending)]))
                pending = []
            }
            let stageStart = result.count
            // Every visible assistant message closes the preceding execution stage.
            for item in segment {
                let kind = item["type"].text
                let unanswered = item["asyncQuestions"].array.contains { $0["answer"] == .null && $0["active"].bool != false }
                let visible = ["userMessage", "steeringUserMessage", "error", "turnDiff"].contains(kind)
                    || kind == "agentMessage" || unanswered
                if visible { flush(); result.append(item) }
                else { pending.append(item) }
            }
            flush()
            let stages = (stageStart..<result.count).filter { result[$0]["type"].text == "processGroup" }
            if stages.count > 1 {
                // The native duration belongs to the whole turn, not each execution stage.
                for index in stages { result[index] = result[index].setting("data", result[index]["data"].setting("durationMs", .null)) }
            }
            segment = []
        }
        for item in items {
            let id = item["turnId"].string
            if item["type"].text == "turn" || id != turnID {
                flushSegment()
                turnID = id; turn = item["type"].text == "turn" ? item : .null
            }
            if item["type"].text != "turn" { segment.append(item) }
        }
        flushSegment()
        return result
    }

    public static func singleActivity(_ group: JSONValue) -> JSONValue? {
        let items = group["items"].array
        return items.count == 1 && items[0]["type"].text != "reasoning" ? items[0] : nil
    }

    public static func bodyItems(_ group: JSONValue) -> [JSONValue] {
        group["items"].array.filter { $0["type"].text != "reasoning" }
    }

    public static func currentActivity(_ group: JSONValue) -> JSONValue? {
        let items = group["items"].array
        return items.last(where: { $0["status"].text == "inProgress" && $0["type"].text != "agentMessage" })
            ?? items.last(where: { $0["type"].text != "agentMessage" }) ?? items.last
    }

    public static func activitySummary(_ item: JSONValue) -> String {
        let data = item["data"]
        switch item["type"].text {
        case "commandExecution":
            let command = data["command"].string ?? item["text"].text
            return command.isEmpty ? "运行命令" : "运行 " + command
        case "reasoning": return item["text"].text.isEmpty ? "思考中" : item["text"].text
        case "fileChange":
            let paths = data["changes"].array.compactMap { $0["path"].string }
            return paths.isEmpty ? "修改文件" : "修改 " + paths.joined(separator: "、")
        case "webSearch": return data["query"].text.isEmpty ? "搜索网页" : "搜索 " + data["query"].text
        case "mcpToolCall", "dynamicToolCall":
            let name = [data["server"].text, data["tool"].text].filter { !$0.isEmpty }.joined(separator: ".")
            return name.isEmpty ? ConversationPresentation.activityText(item) : "使用 " + name
        default: return ConversationPresentation.activityText(item)
        }
    }

    public static func symbol(_ item: JSONValue) -> String {
        switch item["type"].text {
        case "reasoning": "sparkles"
        case "fileChange", "turnDiff": "doc.text"
        case "webSearch": "magnifyingglass"
        case "commandExecution": "terminal"
        default: "wrench.and.screwdriver"
        }
    }

    public static func summaryLabel(_ group: JSONValue) -> AttributedString {
        let text = summary(group)
        guard let current = currentActivity(group) else { return AttributedString(text) }
        return ConversationPresentation.activityLabel(current, text: text)
    }

    public static func summary(_ group: JSONValue) -> String {
        if group["active"].bool == true, let current = currentActivity(group) {
            return current["type"].text == "agentMessage" ? current["text"].text : activitySummary(current)
        }
        if case .number(let ms) = group["data"]["durationMs"], ms.isFinite, ms >= 0, ms < Double(Int.max) {
            let seconds = Int(ms / 1000)
            return seconds >= 60 ? "用时 \(seconds / 60)分\(seconds % 60)秒" : "用时 \(seconds)秒"
        }
        var labels: [String] = []
        for item in bodyItems(group) {
            let label: String
            switch item["type"].text {
            case "commandExecution": label = "运行命令"
            case "fileChange", "turnDiff": label = "修改文件"
            case "webSearch": label = "搜索网页"
            case "mcpToolCall", "dynamicToolCall", "functionCallOutput": label = "使用工具"
            case "subAgentActivity", "collabAgentToolCall": label = "Agent 活动"
            default: label = activitySummary(item)
            }
            if !labels.contains(label) { labels.append(label) }
        }
        return labels.isEmpty ? currentActivity(group).map(activitySummary) ?? "执行过程" : labels.joined(separator: "、")
    }
}
