import Foundation

/// Native latestTokenUsageInfo; no character-count estimates or guessed model limits.
public struct ContextUsage: Equatable, Sendable {
    public let used: Int
    public let capacity: Int
    public init?(_ value: JSONValue) {
        guard let capacity = value["modelContextWindow"].int, capacity > 0,
              let used = value["last"]["totalTokens"].int, used >= 0 else { return nil }
        self.used = used; self.capacity = capacity
    }
    public var fraction: Double { min(1, Double(used) / Double(capacity)) }
    public var remaining: Int { max(0, capacity - used) }
    public var percentage: Int { Int((fraction * 100).rounded()) }
}
