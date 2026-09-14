import Foundation

public struct ConversationContentContext: Sendable, Equatable {
    public let parentID: String?
    public var isReadOnly: Bool { parentID != nil }
    public init(parentID: String? = nil) { self.parentID = parentID }
    public func resourcePath(threadID: String, kind: String, id: String) -> String {
        let base = "/api/\(parentID == nil ? "threads" : "side-chats")/\(ConsoleAddress.component(threadID))/\(kind)/\(ConsoleAddress.component(id))"
        return base + (parentID.map { "?parentId=" + ConsoleAddress.component($0) } ?? "")
    }
}
