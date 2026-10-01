import Foundation

public struct ConversationDraft: Equatable, Sendable {
    public var text: String
    public var images: [String]
    public var skills: [SkillReference]
    public init(text: String = "", images: [String] = [], skills: [SkillReference] = []) { self.text = text; self.images = images; self.skills = skills }
    /// Clear only the content submitted, preserving edits made while awaiting a reply.
    public mutating func didSubmit(_ sent: ConversationDraft) {
        if text == sent.text { text = "" }
        if images == sent.images { images = [] }
        if skills == sent.skills { skills = [] }
    }
}

public enum ComposerAction: Equatable, Sendable {
    case send, pause, restart, unavailable
    public static func resolve(text: String, hasImages: Bool, running: Bool, interrupted: Bool) -> Self {
        if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || hasImages { return .send }
        if running { return .pause }
        return interrupted ? .restart : .unavailable
    }
}
