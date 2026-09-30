import Foundation

/// Only changes actually present in the requested history window. No filesystem reads.
public enum ConversationChanges {
    /// Insert a completed turn's card after its last visible row.
    public static func timeline(_ grouped: [JSONValue], source: [JSONValue]) -> [JSONValue] {
        var turnStatuses: [String: String] = [:]
        for item in source where item["type"].text == "turn" {
            turnStatuses[item["turnId"].text] = item["status"].text
        }
        var changes: [String: [JSONValue]] = [:]
        for item in source where ["fileChange", "turnDiff"].contains(item["type"].text) {
            guard let turn = item["turnId"].string, !turn.isEmpty else { continue }
            changes[turn, default: []].append(item)
        }
        var lastRows: [String: Int] = [:]
        for (index, item) in grouped.enumerated() {
            if let turn = item["turnId"].string { lastRows[turn] = index }
        }
        var result: [JSONValue] = []
        for (index, item) in grouped.enumerated() {
            result.append(item)
            let turn = item["turnId"].text
            guard turnStatuses[turn] == "completed", lastRows[turn] == index,
                  let entries = changes[turn] else { continue }
            let history: JSONValue = .object(["timeline": .array(entries)])
            guard hasChanges(history) else { continue }
            result.append(.object(["id": .string("carryon:changes:" + turn),
                "type": .string("changesSummary"), "turnId": .string(turn), "history": history]))
        }
        return result
    }
    public struct File: Identifiable, Equatable, Sendable {
        public let path: String
        public let entries: [JSONValue]
        public var id: String { path }
        /// Counts recorded patches, not the current working-tree diff.
        public let lineCounts: LineCounts?
        init(path: String, entries: [JSONValue]) {
            self.path = path; self.entries = entries
            lineCounts = Self.countLines(entries)
        }
        private static func countLines(_ entries: [JSONValue]) -> LineCounts? {
            var total = LineCounts()
            for entry in entries {
                guard !["failed", "declined"].contains(entry["status"].text),
                      let counts = ConversationChanges.lineCounts(entry["data"]["changes"].array.first?["diff"].text ?? "") else { return nil }
                total.added += counts.added; total.removed += counts.removed
            }
            return total
        }
    }
    public struct LineCounts: Equatable, Sendable {
        public var added = 0
        public var removed = 0
        public init(added: Int = 0, removed: Int = 0) {
            self.added = added; self.removed = removed
        }
    }
    public struct Snapshot: Equatable, Sendable {
        public let files: [File]
        public let summaries: [JSONValue]
        public let totals: LineCounts?
        public var hasChanges: Bool { !files.isEmpty || !summaries.isEmpty }
        public init(_ history: JSONValue = .null) {
            files = ConversationChanges.files(history)
            summaries = ConversationChanges.summaries(history)
            let counts = files.compactMap(\.lineCounts)
            totals = !files.isEmpty && counts.count == files.count ? counts.reduce(into: LineCounts()) {
                $0.added += $1.added; $0.removed += $1.removed
            } : nil
        }
    }
    public static func lineCounts(_ diff: String) -> LineCounts? {
        guard !diff.isEmpty else { return nil }
        let lines = diff.components(separatedBy: .newlines)
        let hasHunks = lines.contains { $0.hasPrefix("@@ ") }
        var inHunk = !hasHunks, recognized = false, counts = LineCounts()
        for line in lines {
            if line.hasPrefix("diff --git ") { inHunk = !hasHunks; continue }
            if line.hasPrefix("@@ ") { inHunk = true; recognized = true; continue }
            guard inHunk else { continue }
            if !hasHunks && (line.hasPrefix("+++ ") || line.hasPrefix("--- ")) { continue }
            if line.hasPrefix("+") { counts.added += 1; recognized = true }
            else if line.hasPrefix("-") { counts.removed += 1; recognized = true }
        }
        return recognized ? counts : nil
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
    public static func hasChanges(_ history: JSONValue) -> Bool {
        history["timeline"].array.contains {
            ($0["type"].text == "fileChange" && $0["data"]["changes"].array.contains { !$0["path"].text.isEmpty }) ||
            ($0["type"].text == "turnDiff" && !$0["data"]["diff"].text.isEmpty)
        }
    }
}
