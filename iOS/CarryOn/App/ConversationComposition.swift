import Foundation
import CarryOnCore

// Editing and draft submission use the same delivery and permission gates as other actions.
extension AppModel {
    var editingMessage: JSONValue {
        editContext["scope"].text == scope && editContext["threadId"].text == selectedThread?.id ? editContext["item"] : .null
    }
    func beginEditing(_ item: JSONValue) {
        guard let thread = selectedThread, canInteract(.edit), state == "idle", item["turnId"] == history["controls"]["lastTurnId"] else { return }
        if editingMessage == .null {
            editContext = .object(["scope": .string(scope), "threadId": .string(thread.id),
                "draft": .string(draft), "images": .array(draftImages.map(JSONValue.string)), "item": item])
        }
        draft = history["controls"]["lastUserText"].text
        draftImages = []
    }
    func cancelEditing() {
        guard editingMessage != .null else { return }
        draft = editContext["draft"].text; draftImages = editContext["images"].array.compactMap(\.string)
        editContext = .null
    }
    func compose(images: [JSONValue] = []) async -> Bool {
        guard let thread = selectedThread else { return false }
        let text = draft
        let capturedKey = scope + "\n" + thread.id
        let sent = ConversationDraft(text: text, images: images.compactMap(\.string))
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !images.isEmpty else { return false }
        var body: JSONValue = .object(["prompt": .string(text)])
        if !images.isEmpty { body = body.setting("images", .array(images)) }
        let edit = editingMessage
        let success: Bool
        if edit != .null {
            success = await operation("edit", fields: ["turnId": edit["turnId"], "prompt": .string(text), "confirmed": .bool(true)])
        } else {
            success = await write(path: "/api/threads/\(ConsoleAddress.component(thread.id))/compose", target: thread.id, body: body, draftSubmission: true)
        }
        if success, edit != .null {
            if editingMessage == edit { cancelEditing() }
            return true
        }
        if success {
            var current = ConversationDraft(text: draftStore.texts[capturedKey] ?? "", images: draftStore.images[capturedKey] ?? [])
            current.didSubmit(sent)
            draftStore.texts[capturedKey] = current.text; draftStore.images[capturedKey] = current.images
            draftStore.save()
        }
        return success
    }
    func operation(_ action: String, fields: [String: JSONValue] = [:]) async -> Bool {
        guard let thread = selectedThread else { return false }
        return await perform(action, target: .init(scope: scope, threadID: thread.id), fields: fields)
    }
}
