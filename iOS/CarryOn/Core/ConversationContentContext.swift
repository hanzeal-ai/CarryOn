import Foundation

public struct ConversationContentContext: Sendable, Equatable {
    public let parentID: String?
    public let isReadOnly: Bool
    public init(parentID: String? = nil, isReadOnly: Bool? = nil) {
        self.parentID = parentID; self.isReadOnly = isReadOnly ?? (parentID != nil)
    }
    public func resourcePath(threadID: String, kind: String, id: String) -> String {
        let base = "/api/\(parentID == nil ? "threads" : "side-chats")/\(ConsoleAddress.component(threadID))/\(kind)/\(ConsoleAddress.component(id))"
        return base + (parentID.map { "?parentId=" + ConsoleAddress.component($0) } ?? "")
    }
}
