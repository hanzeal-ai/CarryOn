import SwiftUI
import CarryOnCore

extension AppModel {
    func snapshot(for target: ConversationActionTarget) -> JSONValue {
        let value = target.parentID == nil ? history : sideHistory
        return target.matches(scope: scope, selectedThreadID: selectedThread?.id, sideThreadID: sideThreadID, snapshot: value) ? value : .null
    }
    func canPerform(_ target: ConversationActionTarget) -> Bool {
        let value = snapshot(for: target)
        let failure = target.parentID == nil ? historyFailure : sideHistoryFailure
        let explicitAccess = value["access"]["canInteract"].bool
        let explicitReady = value["access"]["nativeReady"].bool
        let native = value["source"].text == "desktop-snapshot" || explicitReady == true
        let permitted = target.parentID == nil ? explicitAccess != false : explicitAccess == true
        return canWrite && failure == nil && permitted && native
            && explicitReady != false && value["syncing"].bool != true
            && ["idle", "running", "waiting"].contains(value["status"]["state"].text)
    }
    @discardableResult func perform(_ action: String, target: ConversationActionTarget, fields: [String: JSONValue] = [:]) async -> Bool {
        guard canPerform(target) else { error = "会话已切换、只读或尚未就绪"; return false }
        let accepted = await write(path: target.path("operations"), target: target.threadID, body: target.body(fields.merging(["action": .string(action)]) { _, new in new }), awaitCompletion: true)
        return accepted && snapshot(for: target) != .null
    }
    @discardableResult func answer(_ question: JSONValue, text: String, target: ConversationActionTarget) async -> Bool {
        guard canPerform(target) else { return false }
        let records: JSONValue = .array([.object(["questionItemId": question["id"], "question": question["title"], "answer": .string(text)])])
        return await write(path: target.path("compose"), target: target.threadID,
            body: target.body(["prompt": .string("<send_user_message_question_reply>\n" + records.formatted + "\n</send_user_message_question_reply>")]), awaitCompletion: true)
    }
}

struct ConversationStatusLabel: View {
    let state: ConversationState
    var body: some View {
        HStack(spacing: 5) {
            if state.tone == .active { ProgressView().controlSize(.mini) }
            else { Image(systemName: state.symbol) }
            Text(state.label)
        }.font(.caption).foregroundStyle(color).accessibilityElement(children: .combine)
    }
    private var color: Color {
        switch state.tone {
        case .active: Design.link
        case .waiting: .orange
        case .success: .green
        case .failure: .red
        case .neutral: Design.secondary
        }
    }
}
