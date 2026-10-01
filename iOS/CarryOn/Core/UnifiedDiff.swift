import Foundation

/// Locations exist only inside a complete, bounded unified diff hunk.
public enum UnifiedDiff {
    public struct Line: Identifiable, Equatable, Sendable {
        public let id: Int
        public let text: String
        public let old: Int?
        public let new: Int?
        public let kind: Kind
        public enum Kind: Sendable { case context, added, removed, header }
        public var location: String? { new.map { "R\($0)" } ?? old.map { "L\($0)" } }
    }
    public static func lines(_ patch: String) -> [Line] {
        var old = 0, new = 0, oldRemaining = 0, newRemaining = 0
        func range(_ field: Substring) -> (Int, Int)? {
            let parts = field.dropFirst().split(separator: ",")
            guard let first = parts.first, let start = Int(first),
                  let count = parts.count == 2 ? Int(parts[1]) : 1,
                  start <= Int.max - count else { return nil }
            return (start, count)
        }
        return patch.components(separatedBy: "\n").enumerated().map { index, text in
            func header() -> Line { Line(id: index, text: text, old: nil, new: nil, kind: .header) }
            if text.hasPrefix("@@") {
                oldRemaining = 0; newRemaining = 0
                guard text.range(of: #"^@@ -[0-9]+(?:,[0-9]+)? \+[0-9]+(?:,[0-9]+)? @@(?: .*)?$"#, options: .regularExpression) != nil else { return header() }
                let fields = text.split(separator: " ")
                if let left = range(fields[1]), let right = range(fields[2]) {
                    (old, oldRemaining) = left; (new, newRemaining) = right
                }
                return header()
            }
            if text.hasPrefix("\\ No newline") { return header() }
            if text.hasPrefix("+"), newRemaining > 0 {
                let row = Line(id: index, text: text, old: nil, new: new, kind: .added)
                new += 1; newRemaining -= 1; return row
            }
            if text.hasPrefix("-"), oldRemaining > 0 {
                let row = Line(id: index, text: text, old: old, new: nil, kind: .removed)
                old += 1; oldRemaining -= 1; return row
            }
            if text.hasPrefix(" "), oldRemaining > 0, newRemaining > 0 {
                let row = Line(id: index, text: text, old: old, new: new, kind: .context)
                old += 1; new += 1; oldRemaining -= 1; newRemaining -= 1; return row
            }
            oldRemaining = 0; newRemaining = 0
            return header()
        }
    }
}
