import SwiftUI
import CarryOnCore

extension AppModel {
    func loadActivity(_ target: ConversationActionTarget) async throws {
        guard target.isActivity, target.scope == scope, activitySnapshots[target.threadID] != nil else { throw CancellationError() }
        let value = try await deviceRequest(target.path("history") + "?limit=40")
        guard target.scope == scope, activitySnapshots[target.threadID] != nil, value["thread"]["id"].text == target.threadID else { throw CancellationError() }
        guard case .array = value["timeline"] else { throw APIError("动态详情格式不正确") }
        activitySnapshots[target.threadID] = value
    }

    func openActivity(_ record: Record, snapshot: JSONValue, anchor: String?) {
        guard snapshot["thread"]["id"].text == record.id else { return }
        let state = readingState(for: record.id)
        let timeline = ConversationProcess.timeline(snapshot["timeline"].array)
        state.historyLimit = max(state.historyLimit, snapshot["historyWindow"]["limit"].int ?? 40)
        state.visibleCount = max(120, timeline.count)
        state.anchorID = anchor
        state.offset = anchor == nil ? 0 : 21
        open(record)
        history = snapshot; historyRevision += 1
        activityScrollTarget = anchor
        activityRequestKey = snapshot["controls"]["requests"].array.first?.requestKey
    }
}
