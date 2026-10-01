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
        let capturedKey = scope + "\n" + thread.id
        let skills = edit == .null ? draftSkills : []
        guard skills.isEmpty || history["controls"]["supportsSkills"].bool == true else {
            error = "当前会话暂不支持技能，请恢复连接或移除技能后重试"; return false
        }
        if ["running", "waiting"].contains(state), !queueFollowUp, history["controls"]["canSteer"].bool == false {
            error = "当前审查不接受补充指令，请排队发送或等待审查结束"; return false
        }
        let sent = ConversationDraft(text: text, images: images.compactMap(\.string), skills: skills)
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !images.isEmpty || !skills.isEmpty else { return false }
        var body: JSONValue = .object(["prompt": .string(text)])
        if !images.isEmpty { body = body.setting("images", .array(images)) }
        if !skills.isEmpty { body = body.setting("skills", .array(skills.map(\.value))) }
        let success: Bool
        if edit != .null {
            success = await operation("edit", fields: ["turnId": edit["turnId"], "prompt": .string(text), "confirmed": .bool(true)])
        } else if queueFollowUp && ["running", "waiting"].contains(state) {
            guard supportsOperation("queue-add", in: history), history["queue"]["fingerprint"].string != nil else {
                error = "队列尚未同步，请刷新后重试"; return false
            }
            success = await operation("queue-add", fields: ["prompt": .string(text), "images": .array(images),
                "skills": .array(skills.map(\.value)), "queueFingerprint": history["queue"]["fingerprint"]])
        } else {
            success = await write(path: "/api/threads/\(ConsoleAddress.component(thread.id))/compose", target: thread.id, body: body, draftSubmission: true)
        }
        if success, edit != .null {
            if editingMessage == edit { cancelEditing() }
            return true
        }
        if success {
            var current = ConversationDraft(text: draftStore.texts[capturedKey] ?? "", images: draftStore.images[capturedKey] ?? [], skills: draftStore.skills[capturedKey] ?? [])
            current.didSubmit(sent)
            draftStore.texts[capturedKey] = current.text; draftStore.images[capturedKey] = current.images; draftStore.skills[capturedKey] = current.skills
            draftStore.save()
        }
        return success
    }
    func operation(_ action: String, fields: [String: JSONValue] = [:]) async -> Bool {
        guard let thread = selectedThread else { return false }
        return await perform(action, target: .init(scope: scope, threadID: thread.id), fields: fields)
    }
}
