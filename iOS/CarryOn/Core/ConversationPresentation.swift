import Foundation

public enum ConversationPresentation {
    public static func visibleReasoning(_ items: [JSONValue]) -> [JSONValue] {
        var result: [JSONValue] = []
        var turnID: String?
        var activeTurn = false
        var latestSummary: Int?
        for item in items {
            let currentTurn = item["turnId"].string
            if item["type"].text == "turn" || currentTurn != turnID {
                turnID = currentTurn
                latestSummary = nil
                activeTurn = item["type"].text == "turn" && item["status"].text == "inProgress"
            }
            guard item["type"].text == "reasoning" else { result.append(item); continue }
            if !item["text"].text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                latestSummary = result.count
                result.append(item)
            } else if activeTurn && item["status"].text == "inProgress" {
                if let latestSummary {
                    result[latestSummary] = result[latestSummary].setting("status", .string("inProgress"))
                } else {
                    result.append(item.setting("text", .string("思考中")))
                }
            }
        }
        return result
    }

    public static func activityText(_ item: JSONValue) -> String {
        let data = item["data"]
        for value in [item["text"], data["command"], data["query"], data["path"], data["explanation"]] {
            if let text = value.string, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return text }
        }
        let paths = data["changes"].array.compactMap { $0["path"].string }
        if !paths.isEmpty { return paths.joined(separator: ", ") }
        return item["title"].string ?? item["type"].text
    }

    public static func activityLabel(_ item: JSONValue) -> AttributedString {
        let text = activityText(item)
        // Shell glob and operator characters are literal command content.
        guard item["type"].text != "commandExecution" else { return AttributedString(text) }
        return (try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
    }

    public static func hasActivityDetails(_ item: JSONValue) -> Bool {
        item["supported"].bool == false || (item["data"].object ?? [:]).contains { key, value in
            !["status", "completed"].contains(key) && value != .null && value != .string("") && value != .array([]) && value != .object([:])
        }
    }

    public static func attachmentDisplayText(_ item: JSONValue) -> String {
        let text = item["text"].text
        guard let regex = try? NSRegularExpression(pattern: #"!?\[([^\]\n]*)\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)"#) else { return text }
        var output = text
        for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
            guard let full = Range(match.range, in: output), let labelRange = Range(match.range(at: 1), in: text), let targetRange = Range(match.range(at: 2), in: text) else { continue }
            let target = String(text[targetRange]).trimmingCharacters(in: CharacterSet(charactersIn: "<>"))
            let path = (target.removingPercentEncoding ?? target).replacingOccurrences(of: #":\d+(?::\d+)?$"#, with: "", options: .regularExpression)
            if let ref = item["artifacts"].array.first(where: { $0["path"].text == path }) {
                let name = ref["name"].text.isEmpty ? String(text[labelRange]) : ref["name"].text
                output.replaceSubrange(full, with: "[" + name.replacingOccurrences(of: "]", with: "\\]") + "](carryon-artifact:" + ref["id"].text + ")")
            }
        }
        return output
    }

    public static func referencedArtifactIDs(_ item: JSONValue) -> Set<String> {
        let rendered = attachmentDisplayText(item)
        return Set(item["artifacts"].array.filter { rendered.contains("(carryon-artifact:" + $0["id"].text + ")") }.map { $0["id"].text })
    }

}
