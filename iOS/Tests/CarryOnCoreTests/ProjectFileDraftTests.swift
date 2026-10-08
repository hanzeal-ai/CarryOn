import Foundation
import Testing
@testable import CarryOnCore

private let fileReference = ProjectFileReference(name: "source.swift", path: "/project/source.swift", query: "source")

@Test func fileDraftProjectionAndRequestPermissionsRemainDistinctFromSkills() {
    let draft = ConversationDraft(text: "检查", files: [fileReference])
    #expect(draft.prompt == "检查")
    #expect(fileReference.value["query"].text == "source")
    #expect(WorkspaceCapability.request(path: "/api/threads/t/files/search?query=source") == [.files])
    #expect(WorkspaceCapability.request(path: "/api/threads/t/compose", body: .object(["files": .array([fileReference.value])])) == [.send, .files])
    #expect(WorkspaceCapability.request(path: "/api/threads/t/operations", body: .object(["action": .string("queue-add"), "files": .array([fileReference.value])])) == [.send, .files])
}

@Test @MainActor func fileDraftRecoveryClearsOnlyExactConfirmedSelection() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: root) }
    let store = DraftStore(file: root.appendingPathComponent("drafts.json")) { _, _ in Issue.record("Unexpected draft error") }
    let scope = "account/device", key = scope + "\nthread"
    await store.load(scope: scope)
    store.texts[key] = "检查"; store.files[key] = [fileReference]
    store.submissions["original"] = .init(scope: scope, threadID: "thread", draft: .init(text: "检查", files: [fileReference]))
    #expect(await store.flush())
    store.reset(); await store.load(scope: "other"); #expect(store.files.isEmpty)
    store.reset(); await store.load(scope: scope)
    #expect(store.files[key] == [fileReference]); #expect(store.submissions["original"]?.draft.files == [fileReference])
    let later = ProjectFileReference(name: "later.swift", path: "/project/later.swift", query: "later")
    store.files[key]?.append(later)
    let accepted: JSONValue = .object(["id": .string("original"), "threadId": .string("thread"), "state": .string("accepted")])
    #expect(store.reconcileSubmission(scope: scope, job: accepted))
    #expect(store.files[key] == [fileReference, later]); #expect(store.texts[key] == "")
    store.submissions["same"] = .init(scope: scope, threadID: "thread", draft: .init(files: [fileReference, later]))
    #expect(store.reconcileSubmission(scope: scope, job: accepted.setting("id", .string("same"))))
    #expect(store.files[key]?.isEmpty == true)
}
