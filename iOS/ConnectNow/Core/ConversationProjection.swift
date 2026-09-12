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
    public mutating func set(_ key: String, _ value: JSONValue) {
        if let revision = value["historyRevision"].string, entries[key]?.value["historyRevision"].string == revision {
            _ = get(key); return
        }
        remove(key)
        guard let size = try? value.encoded().count, size <= maxBytes else { return }
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
