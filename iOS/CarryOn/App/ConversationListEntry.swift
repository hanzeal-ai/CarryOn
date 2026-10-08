import Foundation
import CarryOnCore

/// The item snapshot belongs to this projection; body updates live in its shared presentation.
struct ConversationListEntry: Identifiable, Equatable {
    let id: String
    var configuration = UUID()
    var itemSnapshot: JSONValue?
    var presentation: TimelineRowPresentation?
    var supplemental: JSONValue?
    var canAskSide = false
    var canEdit = false

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.id == rhs.id && lhs.configuration == rhs.configuration
    }
}
