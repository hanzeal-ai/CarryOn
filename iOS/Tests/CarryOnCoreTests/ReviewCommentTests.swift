import Foundation
import Testing
@testable import CarryOnCore

private let reviewPatch = "@@ -1 +1 @@\n-old()\n+new()"
private func reviewNote(_ text: String = "请检查边界", source: String = "native-item") -> ReviewComment {
    ReviewComment(sourceID: source, path: "src/main.swift", patch: reviewPatch, line: UnifiedDiff.lines(reviewPatch)[2], text: text)!
}

@Test func reviewCommentRequiresActualHunkLineAndNativeSource() {
    let line = UnifiedDiff.lines(reviewPatch)[2]
    #expect(ReviewComment(sourceID: "", path: "src/main.swift", patch: reviewPatch, line: line, text: "x") == nil)
    #expect(ReviewComment(sourceID: "item", path: "src/main.swift", patch: "@@ -1 +1 @@\n-old()\n+other()", line: line, text: "x") == nil)
    #expect(ReviewComment(sourceID: "item", path: "src/main.swift", patch: reviewPatch, line: UnifiedDiff.lines(reviewPatch)[0], text: "x") == nil)
}

@Test func reviewCommentDistinguishesSamePathAndLineInDifferentChanges() {
    let first = reviewNote(source: "turn-one/item")
    let second = reviewNote(source: "turn-two/item")
    #expect(first.path == second.path && first.location == second.location)
    #expect(first.sourceID != second.sourceID)
    #expect(ReviewComment.patchIdentity(reviewPatch) != ReviewComment.patchIdentity(reviewPatch + "\n"))
}

@Test func commentProjectionAppendsAfterInlineReferenceText() {
    let note = reviewNote("说明 **原文** 👋")
    let draft = ConversationDraft(text: "先检查 Review 引用", comments: [note])
    #expect(draft.prompt == "先检查 Review 引用\n\n关于已加载改动 src/main.swift（R1）：\n+new()\n说明 **原文** 👋")
    #expect(ConversationDraft(comments: [note]).prompt == note.prompt)
}

@Test func confirmingCommentsPreservesEditsAndNewComments() {
    let unchanged = reviewNote("不变"), changing = reviewNote("发送时正文")
    let sent = ConversationDraft(text: "原正文", comments: [unchanged, changing])
    var edited = changing; edited.text = "等待时继续修改"
    let added = reviewNote("新增")
    var current = ConversationDraft(text: "新的正文", comments: [unchanged, edited, added])
    current.didSubmit(sent)
    #expect(current.text == "新的正文")
    #expect(current.comments == [edited, added])
    var exact = sent; exact.didSubmit(sent)
    #expect(exact.comments.isEmpty && exact.text.isEmpty)
}

@Test @MainActor func reviewCommentsPersistAndStayScopedAfterReset() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = DraftStore(file: directory.appendingPathComponent("drafts.json")) { _, _ in Issue.record("Unexpected save error") }
    let note = reviewNote()
    await store.load(scope: "account-a")
    store.comments["workspace-a\nthread-a"] = [note]
    store.texts["workspace-a\nthread-a"] = "正文"
    store.reset(); #expect(await store.flush())
    await store.load(scope: "account-b"); #expect(store.comments.isEmpty)
    await store.load(scope: "account-a")
    #expect(store.comments["workspace-a\nthread-a"] == [note])
    #expect(store.comments["workspace-a\nthread-b"] == nil)
    store.comments["workspace-a\nthread-a"] = []; #expect(await store.flush())
    await store.load(scope: "account-a"); #expect(store.comments["workspace-a\nthread-a", default: []].isEmpty)
    #expect(store.texts["workspace-a\nthread-a"] == "正文")
}

@Test @MainActor func failedCommentSaveRemainsRecoverable() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let parent = directory.appendingPathComponent("blocked")
    let store = DraftStore(file: parent.appendingPathComponent("drafts.json")) { _, _ in }
    await store.load(scope: "a")
    let note = reviewNote(); store.comments["thread"] = [note]
    store.submissions["pending"] = DraftSubmission(scope: "a", threadID: "thread", draft: ConversationDraft(comments: [note]))
    try Data().write(to: parent)
    #expect(!(await store.flush()))
    store.reset(); await store.load(scope: "b"); #expect(store.comments.isEmpty && store.submissions.isEmpty)
    store.reset(); try FileManager.default.removeItem(at: parent)
    await store.load(scope: "a"); #expect(store.comments["thread"] == [note] && store.submissions["pending"]?.draft.comments == [note])
    #expect(await store.flush())
}

@Test @MainActor func commentIdentityDoesNotChangeUnknownRequestFingerprint() throws {
    let suite = "review-unknown-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    let journal = PendingWrites(defaults: defaults)
    let first = ConversationDraft(comments: [reviewNote()]), second = ConversationDraft(comments: [reviewNote()])
    #expect(first.comments[0].id != second.comments[0].id)
    #expect(first.prompt == second.prompt)
    let a = try journal.requestID(scope: "scope", target: "thread", path: "/compose", body: .object(["prompt": .string(first.prompt)]))
    let b = try journal.requestID(scope: "scope", target: "thread", path: "/compose", body: .object(["prompt": .string(second.prompt)]))
    #expect(a == b)
}

@Test @MainActor func queriedReceiptClearsExactPersistedDraftAndPreservesLaterEdits() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let file = directory.appendingPathComponent("drafts.json"), scope = "account/server/device", key = "account/server/device\nthread"
    let sent = ConversationDraft(text: "正文", images: ["image"], comments: [reviewNote()])
    let store = DraftStore(file: file) { _, _ in Issue.record("Unexpected save error") }
    await store.load(scope: scope)
    store.texts[key] = sent.text; store.images[key] = sent.images; store.comments[key] = sent.comments
    store.submissions["request"] = DraftSubmission(scope: scope, threadID: "thread", draft: sent)
    #expect(await store.flush())
    store.reset(); await store.load(scope: scope)
    let job: JSONValue = .object(["id": .string("request"), "threadId": .string("thread"), "state": .string("accepted")])
    #expect(!store.reconcileSubmission(scope: "other", job: job))
    #expect(!store.reconcileSubmission(scope: scope, job: job.setting("threadId", .string("other"))))
    #expect(!store.reconcileSubmission(scope: scope, job: job.setting("state", .string("uncertain"))))
    var changed = sent.comments[0]; changed.text = "后改"
    let added = reviewNote("新增")
    store.texts[key] = "新正文"; store.comments[key] = [changed, added]
    #expect(store.reconcileSubmission(scope: scope, job: job))
    #expect(store.texts[key] == "新正文" && store.images[key] == [] && store.comments[key] == [changed, added])
    #expect(store.submissions.isEmpty)
    #expect(await store.flush())
    store.reset(); await store.load(scope: scope)
    #expect(store.comments[key] == [changed, added] && store.submissions.isEmpty)
    store.submissions["exact"] = DraftSubmission(scope: scope, threadID: "thread", draft: ConversationDraft(text: "新正文", comments: [changed, added]))
    #expect(store.reconcileSubmission(scope: scope, job: job.setting("id", .string("exact"))))
    #expect(store.texts[key] == "" && store.comments[key] == [])
}

@Test @MainActor func failedReceiptKeepsAuthoringDraftAndReleasesOnlyItsSnapshot() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = DraftStore(file: directory.appendingPathComponent("drafts.json")) { _, _ in }
    await store.load(scope: "scope")
    let note = reviewNote(), key = "scope\nthread"
    store.comments[key] = [note]
    store.submissions["failed"] = DraftSubmission(scope: "scope", threadID: "thread", draft: ConversationDraft(comments: [note]))
    let job: JSONValue = .object(["id": .string("failed"), "threadId": .string("thread"), "state": .string("failed")])
    #expect(store.reconcileSubmission(scope: "scope", job: job))
    #expect(store.comments[key] == [note] && store.submissions.isEmpty)
    #expect(!store.reconcileSubmission(scope: "scope", job: job))
}

@Test func bodyAnnotationsDecodeOldDraftsAndProjectWithoutDiffMetadata() throws {
    let old = try JSONDecoder().decode(ConversationDraft.self, from: Data(#"{"text":"旧草稿","images":[],"skills":[],"comments":[]}"#.utf8))
    #expect(old.annotations == nil && old.prompt == "旧草稿")
    #expect(MessageAnnotation(sourceID: "", text: "引用") == nil)
    #expect(MessageAnnotation(sourceID: "message", text: " \n") == nil)
    let note = try #require(MessageAnnotation(sourceID: "message", text: "选中 **正文** 👋"))
    let draft = ConversationDraft(text: "请解释", annotations: [note])
    #expect(draft.prompt == "请解释\n\n关于以下会话内容：\n选中 **正文** 👋")
    #expect(try JSONDecoder().decode(ConversationDraft.self, from: JSONEncoder().encode(draft)) == draft)
}

@Test @MainActor func bodyAnnotationsPersistAndReceiptKeepsLaterAdditions() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = DraftStore(file: directory.appendingPathComponent("draft.json")) { _, _ in Issue.record("Unexpected save failure") }
    let note = try #require(MessageAnnotation(sourceID: "message", text: "正文批注"))
    let added = try #require(MessageAnnotation(sourceID: "other-message", text: "稍后添加"))
    await store.load(scope: "account")
    let key = "account\nthread"
    store.annotations[key] = [note]
    store.submissions["request"] = DraftSubmission(scope: "account", threadID: "thread", draft: .init(annotations: [note]))
    #expect(await store.flush())
    await store.load(scope: "other"); #expect(store.annotations.isEmpty)
    await store.load(scope: "account"); #expect(store.annotations[key] == [note])
    store.annotations[key]?.append(added)
    let job: JSONValue = .object(["id": .string("request"), "threadId": .string("thread"), "state": .string("uncertain")])
    #expect(!store.reconcileSubmission(scope: "account", job: job))
    #expect(store.annotations[key] == [note, added])
    #expect(!store.reconcileSubmission(scope: "other", job: job.setting("state", .string("accepted"))))
    #expect(store.reconcileSubmission(scope: "account", job: job.setting("state", .string("accepted"))))
    #expect(store.annotations[key] == [added])
    #expect(await store.flush())
    await store.load(scope: "account"); #expect(store.annotations[key] == [added])
}

@Test @MainActor func bodyAnnotationSaveFailureKeepsPendingDraftRecoverable() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let parent = directory.appendingPathComponent("blocked")
    let store = DraftStore(file: parent.appendingPathComponent("draft.json")) { _, _ in }
    await store.load(scope: "account")
    let note = try #require(MessageAnnotation(sourceID: "answer", text: "必须保留"))
    store.annotations["account\nthread"] = [note]
    store.submissions["request"] = .init(scope: "account", threadID: "thread", draft: .init(annotations: [note]))
    try Data().write(to: parent)
    #expect(!(await store.flush()))
    await store.load(scope: "other"); #expect(store.annotations.isEmpty)
    try FileManager.default.removeItem(at: parent)
    await store.load(scope: "account")
    #expect(store.annotations["account\nthread"] == [note])
    #expect(store.submissions["request"]?.draft.annotations == [note])
    #expect(await store.flush())
}
