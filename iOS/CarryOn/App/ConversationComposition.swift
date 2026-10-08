import Foundation
import CarryOnCore

// Editing and draft submission use the same delivery and permission gates as other actions.
extension AppModel {
    var editingMessage: JSONValue {
        editContext["scope"].text == scope && editContext["threadId"].text == selectedThread?.id ? editContext["item"] : .null
    }
    var editingDraft: String {
        get { editingMessage == .null ? "" : editContext["text"].text }
        set { if editingMessage != .null { editContext = editContext.setting("text", .string(newValue)) } }
    }
    func beginEditing(_ item: JSONValue) {
        guard let thread = selectedThread, canInteract(.edit), state == "idle", item["turnId"] == history["controls"]["lastTurnId"] else { return }
        editContext = .object(["scope": .string(scope), "threadId": .string(thread.id),
            "text": history["controls"]["lastUserText"], "item": item])
    }
    func cancelEditing() {
        guard editingMessage != .null else { return }
        editContext = .null
    }
    func compose(images: [JSONValue] = [], queueFollowUp: Bool = false) async -> Bool {
        guard let thread = selectedThread else { return false }
        let edit = editingMessage
        let text = edit == .null ? draft : editingDraft
        let skills = edit == .null ? draftSkills : []
        guard skills.allSatisfy(\.isMention) || history["controls"]["supportsSkills"].bool == true else {
            error = "当前会话暂不支持技能，请恢复连接或移除技能后重试"; return false
        }
        guard !skills.contains(where: \.isMention) || history["controls"]["supportsMentions"].bool == true else {
            error = "当前会话暂不支持应用或插件引用，请恢复连接或移除引用后重试"; return false
        }
        if ["running", "waiting"].contains(state), !queueFollowUp, history["controls"]["canSteer"].bool == false {
            error = "当前审查不接受补充指令，请排队发送或等待审查结束"; return false
        }
        let files = edit == .null ? draftFiles : []
        guard files.isEmpty || (history["controls"]["supportsFileReferences"].bool == true && allows(.files)) else {
            error = "当前会话暂不支持项目文件引用，请恢复权限或移除引用后重试"; return false
        }
        let comments = edit == .null ? draftComments : []
        let sent = ConversationDraft(text: text, images: images.compactMap(\.string), skills: skills, comments: comments, files: files)
        guard !sent.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !images.isEmpty || !skills.isEmpty || !files.isEmpty else { return false }
        let wireText = ConversationDraft(text: text.replacingOccurrences(of: ComposerDocument.marker, with: ""), comments: comments).prompt
        var body: JSONValue = .object(["prompt": .string(wireText)])
        if !images.isEmpty { body = body.setting("images", .array(images)) }
        if !skills.isEmpty { body = body.setting("skills", .array(skills.filter { !$0.isMention }.map(\.value))) }
        if skills.contains(where: \.isMention) { body = body.setting("mentions", .array(skills.filter(\.isMention).map(\.value))) }
        if !files.isEmpty { body = body.setting("files", .array(files.map(\.value))) }
        let success: Bool
        if edit != .null {
            success = await operation("edit", fields: ["turnId": edit["turnId"], "prompt": .string(text), "confirmed": .bool(true)])
        } else if queueFollowUp && ["running", "waiting"].contains(state) {
            guard supportsOperation("queue-add", in: history), history["queue"]["fingerprint"].string != nil else {
                error = "队列尚未同步，请刷新后重试"; return false
            }
            success = await perform("queue-add", target: .init(scope: scope, threadID: thread.id), fields: ["prompt": .string(wireText), "images": .array(images),
                "skills": .array(skills.filter { !$0.isMention }.map(\.value)), "mentions": .array(skills.filter(\.isMention).map(\.value)), "files": .array(files.map(\.value)), "queueFingerprint": history["queue"]["fingerprint"]], authoredDraft: sent)
        } else {
            success = await write(path: "/api/threads/\(ConsoleAddress.component(thread.id))/compose", target: thread.id, body: body, draftSubmission: true, authoredDraft: sent)
        }
        if success, edit != .null {
            if editingMessage == edit { cancelEditing() }
            return true
        }
        return success
    }
    func operation(_ action: String, fields: [String: JSONValue] = [:]) async -> Bool {
        guard let thread = selectedThread else { return false }
        return await perform(action, target: .init(scope: scope, threadID: thread.id), fields: fields)
    }
}
