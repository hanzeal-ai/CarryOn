import Foundation

/// Display-only, bounded by encoded bytes and least recently used access.
public struct DisplayHistoryCache {
    private var entries: [String: (value: JSONValue, bytes: Int)] = [:]
    private var order: [String] = []
    public private(set) var bytes = 0
    private let maxEntries: Int
    private let maxBytes: Int
    public init(maxEntries: Int = 8, maxBytes: Int = 8 * 1024 * 1024) {
        self.maxEntries = maxEntries; self.maxBytes = maxBytes
    }
    public mutating func get(_ key: String) -> JSONValue? {
        guard let value = entries[key]?.value else { return nil }
        order.removeAll { $0 == key }; order.append(key)
        return value
    }
    /// Byte measurement is supplied by the background projection, never encoded on the UI thread.
    public mutating func set(_ key: String, _ value: JSONValue, encodedBytes size: Int) {
        if let revision = value["historyRevision"].string, entries[key]?.value["historyRevision"].string == revision {
            _ = get(key); return
        }
        remove(key)
        guard size >= 0, size <= maxBytes else { return }
        entries[key] = (value, size); order.append(key); bytes += size
        while entries.count > maxEntries || bytes > maxBytes {
            guard let first = order.first else { break }
            remove(first)
        }
    }
    private mutating func remove(_ key: String) {
        if let old = entries.removeValue(forKey: key) { bytes -= old.bytes }
        order.removeAll { $0 == key }
    }
    public mutating func clear() { entries = [:]; order = []; bytes = 0 }
}

public enum OutgoingMessageProjection {
    private static func answers(_ prompt: String) -> [JSONValue] {
        let open = "<send_user_message_question_reply>", close = "</send_user_message_question_reply>"
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.hasPrefix(open), text.hasSuffix(close),
              let value = try? JSONDecoder().decode(JSONValue.self, from: Data(text.dropFirst(open.count).dropLast(close.count).utf8)) else { return [] }
        let records = value.object == nil ? value.array : [value]
        guard !records.isEmpty, records.allSatisfy({ $0["questionItemId"].string != nil && $0["question"].string != nil && $0["answer"].string != nil }) else { return [] }
        return records
    }
    public static func displayText(_ prompt: String) -> String {
        let replies = answers(prompt)
        return replies.isEmpty ? prompt : replies.map { $0["question"].text + "\n" + $0["answer"].text }.joined(separator: "\n\n")
    }
    /// Match native identifiers, never ordinary message text or task completion alone.
    public static func isReflected(_ item: JSONValue, in history: JSONValue) -> Bool {
        let messageID = item["clientMessageId"].string
        let timeline = history["timeline"].array
        if timeline.contains(where: { entry in
            guard ["userMessage", "steeringUserMessage"].contains(entry["type"].text), entry["status"].text != "rejected" else { return false }
            return (messageID != nil && [entry["nativeId"].string, entry["clientMessageId"].string].contains(messageID)) ||
                (item["kind"].text == "message" && item["turnId"].string != nil && entry["turnId"] == item["turnId"])
        }) { return true }
        if history["queue"]["messages"].array.contains(where: { messageID != nil && $0["id"].string == messageID }) { return true }
        let replies = answers(item["prompt"].text)
        let questions = timeline.flatMap { $0["asyncQuestions"].array }
        return !replies.isEmpty && replies.allSatisfy { reply in
            questions.contains { $0["id"] == reply["questionItemId"] && $0["answer"] == reply["answer"] }
        }
    }
    /// Once the live journal is observed, the HTTP admission result cannot roll it back.
    public static func merge(_ previous: JSONValue?, _ update: JSONValue, live: Bool = false) -> JSONValue? {
        guard var fields = previous?.object, update["state"].text != "acknowledged" else { return nil }
        if previous?["live"].bool == true && !live { return previous }
        if case .number(let old) = previous?["updated"], case .number(let new) = update["updated"], new < old { return previous }
        for (key, value) in update.object ?? [:] where key != "created" { fields[key] = value }
        fields["live"] = .bool(live || previous?["live"].bool == true)
        return .object(fields)
    }
}

/// Each transport decodes before its consumer can coalesce complete snapshots.
public struct HistoryWireProjection {
    private var scope: [JSONValue] = []
    private var histories: [String: JSONValue] = [:]
    public init() {}
    public mutating func decode(_ packet: JSONValue) throws -> JSONValue {
        let selected = [packet["subscription"], packet["threadId"], packet["sideThreadId"]]
        if selected != scope || packet["status"]["enabled"].bool == false { histories = [:]; scope = selected }
        var result = packet.object ?? [:], next = histories
        for field in ["history", "sideHistory"] {
            let delta = packet[field + "Delta"]
            if delta != .null {
                guard result[field] == nil, let previous = histories[field], delta["base"] == previous["historyRevision"],
                      let start = delta["start"].int, let count = delta["delete"].int,
                      start >= 0, count >= 0, start <= previous["timeline"].array.count,
                      count <= previous["timeline"].array.count - start,
                      case .array(let items) = delta["items"], let updates = delta["fields"].object,
                      updates["historyRevision"]?.string != nil else { throw APIError("历史版本缺口，需要重新同步") }
                let timeline = previous["timeline"].array
                var fields = previous.object ?? [:]
                let removed = delta["remove"] == .null ? [] : delta["remove"].array
                guard delta["remove"] == .null || { if case .array = delta["remove"] { return true }; return false }(),
                      removed.allSatisfy({ $0.string != nil && !["timeline", "historyRevision"].contains($0.text) }) else { throw APIError("历史增量格式无效") }
                for key in removed { fields.removeValue(forKey: key.text) }
                fields.merge(updates) { _, new in new }
                fields["timeline"] = .array(Array(timeline.prefix(start)) + items + Array(timeline.dropFirst(start + count)))
                if delta["messages"] != .null {
                    let splice = delta["messages"], old = previous["messages"].array
                    guard case .array = previous["messages"], let start = splice["start"].int, let count = splice["delete"].int,
                          start >= 0, count >= 0, start <= old.count, count <= old.count - start,
                          case .array(let items) = splice["items"] else { throw APIError("历史增量格式无效") }
                    fields["messages"] = .array(Array(old.prefix(start)) + items + Array(old.dropFirst(start + count)))
                }
                result[field] = .object(fields); result.removeValue(forKey: field + "Delta")
            }
            next[field] = result[field]
        }
        histories = next
        return .object(result)
    }
}
