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
    func interactionUnavailableReason(_ target: ConversationActionTarget, capability: WorkspaceCapability) -> String? {
        if target.scope != scope { return "工作区已切换，请返回当前工作区后重试" }
        if !authenticated { return "登录已失效，请重新登录" }
        if !connected { return "工作区尚未连接，连接恢复后可操作" }
        if status["enabled"].bool != true { return "Codex 尚未就绪，请在电脑端检查连接" }
        if status["remoteControl"].bool != true { return "工作区为只读，请在电脑端开启远程控制" }
        if !allows(capability) { return "当前账号没有此操作权限，请联系工作区管理员" }
        let value = snapshot(for: target)
        if value["access"]["canInteract"].bool == false { return "此会话为只读，可查看历史记录" }
        if writing { return "正在提交操作，请稍候" }
        if !canPerform(target) { return "会话尚未就绪，请等待同步后重试" }
        return nil
    }
    @discardableResult func perform(_ action: String, target: ConversationActionTarget, fields: [String: JSONValue] = [:]) async -> Bool {
        guard canPerform(target, action: action) else { error = interactionUnavailableReason(target, capability: WorkspaceCapability.operation(action) ?? .view) ?? "当前操作不可用，请刷新会话后重试"; return false }
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
