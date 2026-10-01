import Foundation
import Testing
@testable import CarryOnCore

@Test func skillDraftSubmissionPreservesLaterSelection() {
    let first = SkillReference(name: "first", path: "/project/first/SKILL.md")
    let second = SkillReference(name: "second", path: "/project/second/SKILL.md")
    let sent = ConversationDraft(text: "run", skills: [first])
    var edited = ConversationDraft(text: "run", skills: [first, second])
    edited.didSubmit(sent)
    #expect(edited.text.isEmpty)
    #expect(edited.skills == [first, second])
    var unchanged = sent
    unchanged.didSubmit(sent)
    #expect(unchanged == ConversationDraft())
}

@Test @MainActor func skillDraftPersistsAcrossAccountsWithoutLeakage() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = DraftStore(file: directory.appendingPathComponent("drafts.json")) { _, _ in Issue.record("Unexpected persistence error") }
    let selected = SkillReference(name: "review", path: "/project/review/SKILL.md")
    await store.load(scope: "account-a")
    store.skills["workspace/thread"] = [selected]
    #expect(await store.flush())
    await store.load(scope: "account-b")
    #expect(store.skills.isEmpty)
    store.skills["workspace/thread"] = [.init(name: "other", path: "/other/SKILL.md")]
    #expect(await store.flush())
    await store.load(scope: "account-a")
    #expect(store.skills["workspace/thread"] == [selected])
    store.skills["workspace/thread"] = []
    #expect(await store.flush())
    await store.load(scope: "account-a")
    #expect(store.skills["workspace/thread", default: []].isEmpty)
}
