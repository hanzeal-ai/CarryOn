import SwiftUI
import CarryOnCore

extension AppModel {
    func beginActivity(_ target: ConversationActionTarget, preview: JSONValue) {
        guard target.isActivity, target.scope == scope, activitySnapshots[target.threadID] == nil else { return }
        let cached = displayCache.value(historyCacheKey(target.threadID))
        let turnID = cached["timeline"].array.last { $0["type"].text == "turn" }?["turnId"]
        let matchesTurn = preview["turnId"] == .null || turnID == preview["turnId"]
        let detail = ActivityDetail(history: cached)
        let expectedKind = ActivityDetail.Kind(rawValue: preview["kind"].text)
        let matchesKind = expectedKind == nil || expectedKind == detail.kind
        let hasContent = detail.result != .null || detail.failure != nil || !detail.requests.isEmpty || !detail.questions.isEmpty
        if cached["thread"]["id"].text == target.threadID, case .array = cached["timeline"], matchesTurn, matchesKind, hasContent {
            // Cached content is readable immediately; only a fresh response can
            // supply the native permission and readiness used for an operation.
            activitySnapshots[target.threadID] = cached.setting("access", .object(["canInteract": .bool(false), "nativeReady": .bool(false)]))
        } else { activitySnapshots[target.threadID] = .null }
        activitySnapshotVersions[target.threadID] = UUID()
    }

    func endActivity(_ target: ConversationActionTarget) {
        guard target.scope == scope else { return }
        activitySnapshots.removeValue(forKey: target.threadID)
        activitySnapshotVersions.removeValue(forKey: target.threadID)
    }

    func loadActivity(_ target: ConversationActionTarget) async throws {
        guard target.isActivity, target.scope == scope, activitySnapshots[target.threadID] != nil else { throw CancellationError() }
        let version = UUID()
        activitySnapshotVersions[target.threadID] = version
        let value = try await deviceRequest(target.path("history") + "?limit=40")
        guard !Task.isCancelled, target.scope == scope, activitySnapshots[target.threadID] != nil,
              activitySnapshotVersions[target.threadID] == version, value["thread"]["id"].text == target.threadID else { throw CancellationError() }
        guard case .array = value["timeline"] else { throw APIError("动态详情格式不正确") }
        activitySnapshots[target.threadID] = value
        let bytes = await Task.detached(priority: .utility) { (try? value.encoded().count) ?? -1 }.value
        guard !Task.isCancelled, target.scope == scope, activitySnapshotVersions[target.threadID] == version else { return }
        displayCache.store(value, key: historyCacheKey(target.threadID), bytes: bytes)
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
