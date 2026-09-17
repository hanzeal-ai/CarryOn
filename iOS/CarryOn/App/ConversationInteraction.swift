import SwiftUI
import CarryOnCore

extension AppModel {
    func snapshot(for target: ConversationActionTarget) -> JSONValue {
        if target.isActivity {
            guard target.scope == scope, target.parentID == nil,
                  let value = activitySnapshots[target.threadID], value["thread"]["id"].text == target.threadID else { return .null }
            return value
        }
        let value = target.parentID == nil ? history : sideHistory
        return target.matches(scope: scope, selectedThreadID: selectedThread?.id, sideThreadID: sideThreadID, snapshot: value) ? value : .null
    }
    func canPerform(_ target: ConversationActionTarget) -> Bool {
        let value = snapshot(for: target)
        let failure = target.isActivity ? nil : (target.parentID == nil ? historyFailure : sideHistoryFailure)
        let explicitAccess = value["access"]["canInteract"].bool
        let explicitReady = value["access"]["nativeReady"].bool
        let native = value["source"].text == "desktop-snapshot" || explicitReady == true
        let permitted = target.parentID == nil ? explicitAccess != false : explicitAccess == true
        return canWrite && failure == nil && permitted && native
            && explicitReady != false && value["syncing"].bool != true
            && ["idle", "running", "waiting"].contains(value["status"]["state"].text)
    }
    func canPerform(_ target: ConversationActionTarget, action: String) -> Bool {
        guard let capability = WorkspaceCapability.operation(action) else { return false }
        return canPerform(target) && allows(capability)
    }
    @discardableResult func perform(_ action: String, target: ConversationActionTarget, fields: [String: JSONValue] = [:]) async -> Bool {
        guard canPerform(target, action: action) else { error = "工作区未授权此操作，或会话已切换、只读、尚未就绪"; return false }
        let accepted = await write(path: target.path("operations"), target: target.threadID, body: target.body(fields.merging(["action": .string(action)]) { _, new in new }), awaitCompletion: true)
        if accepted && target.isActivity {
            do { try await loadActivity(target) } catch { report(error, operation: "刷新动态详情", blocking: false) }
        }
        return accepted && snapshot(for: target) != .null
    }
    @discardableResult func answer(_ question: JSONValue, text: String, target: ConversationActionTarget) async -> Bool {
        if target.isActivity {
            do { try await loadActivity(target) }
            catch { report(error, operation: "核对问题状态"); return false }
            guard ActivityDetail(history: snapshot(for: target)).questions.contains(where: { $0["id"] == question["id"] && $0["title"] == question["title"] }) else {
                error = "问题已回答或已结束，请查看最新动态"; return false
            }
        }
        guard canPerform(target), allows(.send) else { return false }
        let records: JSONValue = .array([.object(["questionItemId": question["id"], "question": question["title"], "answer": .string(text)])])
        let accepted = await write(path: target.path("compose"), target: target.threadID,
            body: target.body(["prompt": .string("<send_user_message_question_reply>\n" + records.formatted + "\n</send_user_message_question_reply>")]), awaitCompletion: true)
        if accepted && target.isActivity {
            do { try await loadActivity(target) } catch { report(error, operation: "刷新动态详情", blocking: false) }
        }
        return accepted
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
