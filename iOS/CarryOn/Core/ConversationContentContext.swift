import Foundation

public struct ConversationContentContext: Sendable, Equatable {
    public let parentID: String?
    public let isReadOnly: Bool
    public init(parentID: String? = nil, isReadOnly: Bool = false) {
        self.parentID = parentID; self.isReadOnly = parentID != nil || isReadOnly
    }
    public func resourcePath(threadID: String, kind: String, id: String) -> String {
        let base = "/api/\(parentID == nil ? "threads" : "side-chats")/\(ConsoleAddress.component(threadID))/\(kind)/\(ConsoleAddress.component(id))"
        return base + (parentID.map { "?parentId=" + ConsoleAddress.component($0) } ?? "")
    }
}
