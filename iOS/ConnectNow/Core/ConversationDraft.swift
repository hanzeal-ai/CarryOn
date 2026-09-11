import Foundation

public struct ConversationDraft: Equatable, Sendable {
    public var text: String
    public var images: [String]
    public init(text: String = "", images: [String] = []) { self.text = text; self.images = images }
    /// Clear only the content submitted, preserving edits made while awaiting a reply.
    public mutating func didSubmit(_ sent: ConversationDraft) {
        if text == sent.text { text = "" }
        if images == sent.images { images = [] }
    }
}
