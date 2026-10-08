import SwiftUI

enum CarryOnMessageAction: Hashable, CaseIterable {
    case copy, selectText, edit
    func title() -> String { self == .copy ? "复制原文" : self == .edit ? "编辑消息" : "选择文字" }
    func icon() -> Image { Image(systemName: self == .copy ? "doc.on.doc" : self == .edit ? "pencil" : "text.cursor") }
    static func menuItems(forType type: String, canEdit: Bool) -> [Self] {
        guard ["userMessage", "steeringUserMessage", "agentMessage"].contains(type) else { return [] }
        return canEdit ? [.selectText, .copy, .edit] : [.selectText, .copy]
    }
}
