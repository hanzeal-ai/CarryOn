import Foundation

/// Commands are a composer interaction; execution remains in existing native services.
public struct ComposerCommand: Equatable, Sendable {
    public let name: String
    public let argument: String
    public init?(_ text: String) {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.first == "/" else { return nil }
        let parts = value.dropFirst().split(maxSplits: 1, whereSeparator: { $0.isWhitespace })
        guard let first = parts.first, let initial = first.unicodeScalars.first, (97...122).contains(initial.value),
              first.unicodeScalars.allSatisfy({ (97...122).contains($0.value) || $0 == "-" }) else { return nil }
        name = String(first)
        argument = parts.count > 1 ? String(parts[1]).trimmingCharacters(in: .whitespacesAndNewlines) : ""
    }
    public static let names = ["side", "plan", "review", "compact", "fork", "goal", "model", "status"]
    public static func query(_ text: String) -> String? {
        guard text.first == "/", !text.contains(where: { $0.isWhitespace }), !text.dropFirst().contains("/") else { return nil }
        return String(text.dropFirst())
    }
    public var operation: String? {
        switch name {
        case "side": "side-create"
        case "plan", "model": "settings"
        case "goal": "goal-set"
        case "review", "compact", "fork": name
        default: nil
        }
    }
    public var capability: WorkspaceCapability? {
        switch name {
        case "side", "fork": .create
        case "plan", "model", "compact": .edit
        case "review", "goal": .send
        default: nil
        }
    }
}
