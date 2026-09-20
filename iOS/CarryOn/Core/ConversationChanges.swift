import Foundation

/// Only changes actually present in the requested history window. No filesystem reads.
public enum ConversationChanges {
    public struct File: Identifiable, Equatable, Sendable {
        public let path: String
        public let entries: [JSONValue]
        public var id: String { path }
    }
    public static func files(_ history: JSONValue) -> [File] {
        var order: [String] = [], grouped: [String: [JSONValue]] = [:]
        for item in history["timeline"].array where item["type"].text == "fileChange" {
            for change in item["data"]["changes"].array {
                let path = change["path"].text
                guard !path.isEmpty else { continue }
                if grouped[path] == nil { order.append(path) }
                let entry = item.setting("data", item["data"].setting("changes", .array([change])))
                grouped[path, default: []].append(entry)
            }
        }
        return order.map { File(path: $0, entries: grouped[$0] ?? []) }
    }
    public static func summaries(_ history: JSONValue) -> [JSONValue] {
        history["timeline"].array.filter { $0["type"].text == "turnDiff" && !$0["data"]["diff"].text.isEmpty }
    }
    public static func hasChanges(_ history: JSONValue) -> Bool { !files(history).isEmpty || !summaries(history).isEmpty }
}
