import Foundation
import Testing
@testable import CarryOnCore

private final class CountingPreferences: UserDefaults, @unchecked Sendable {
    var writes = 0
    override func set(_ value: Any?, forKey key: String) {
        writes += 1
        super.set(value, forKey: key)
    }
}

@Test @MainActor func liveJobBatchesPersistOnlyActualChangesOnce() throws {
    let suite = "CarryOn.PerformanceTests." + UUID().uuidString
    let defaults = try #require(CountingPreferences(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    let pending = PendingWrites(defaults: defaults)
    let body: JSONValue = .object(["prompt": .string("hello")])
    let first = try pending.requestID(scope: "a", target: "one", path: "/compose", body: body)
    let second = try pending.requestID(scope: "a", target: "two", path: "/compose", body: body)
    let other = try pending.requestID(scope: "b", target: "one", path: "/compose", body: body)
    let jobs: [JSONValue] = [
        .object(["id": .string(first), "threadId": .string("one"), "state": .string("completed")]),
        .object(["id": .string(second), "threadId": .string("two"), "state": .string("accepted")]),
        .object(["id": .string(other), "threadId": .string("one"), "state": .string("completed")])
    ]
    let before = defaults.writes
    try pending.reconcile(scope: "a", jobs: jobs)
    #expect(defaults.writes == before + 1)
    #expect(!pending.hasPending(scope: "a", target: "one"))
    #expect(!pending.hasPending(scope: "a", target: "two"))
    #expect(pending.hasPending(scope: "b", target: "one"))
    try pending.reconcile(scope: "a", jobs: jobs)
    try pending.resolve(scope: "a", target: "missing", requestID: "missing")
    #expect(defaults.writes == before + 1)
    let restored = PendingWrites(defaults: defaults)
    #expect(try restored.requestID(scope: "b", target: "one", path: "/compose", body: body) == other)
}

@Test func navigationIndexTracksPrecedingUserAcrossProcessGroups() {
    let rows: [JSONValue] = [
        .object(["id": .string("before"), "type": .string("agentMessage")]),
        .object(["id": .string("user"), "type": .string("userMessage")]),
        .object(["id": .string("process"), "type": .string("processGroup")]),
        .object(["id": .string("followup"), "type": .string("steeringUserMessage")]),
        .object(["id": .string("reply"), "type": .string("agentMessage")])
    ]
    let index = ConversationPresentation.NavigationIndex(rows)
    #expect(index.messages.map { $0["id"].text } == ["user", "followup"])
    #expect(index.selectionByID["before"] == nil)
    #expect(index.selectionByID["process"] == "user")
    #expect(index.selectionByID["reply"] == "followup")
    #expect(index.selectionByID["removed"] == nil)
    #expect(ConversationPresentation.NavigationIndex(Array(rows.prefix(3))).selectionByID["reply"] == nil)
}

@Test func changeSnapshotKeepsCountsAndUnknownPatchSemantics() {
    func change(_ path: String, _ diff: String) -> JSONValue {
        .object(["type": .string("fileChange"), "data": .object([
            "changes": .array([.object(["path": .string(path), "diff": .string(diff)])])])])
    }
    let known = change("one.swift", "@@ -1 +1,2 @@\n-old\n+new\n+more")
    let history: JSONValue = .object(["timeline": .array([known, known])])
    let first = ConversationChanges.Snapshot(history)
    #expect(first.files.count == 1)
    #expect(first.files.first?.entries.count == 2)
    #expect(first.totals == .init(added: 4, removed: 2))
    let second = ConversationChanges.Snapshot(.object(["timeline": .array([known, change("two.swift", "")])]))
    #expect(second.totals == nil)
    #expect(second.files.first?.lineCounts == .init(added: 2, removed: 1))
    #expect(second.hasChanges)
    #expect(!ConversationChanges.Snapshot().hasChanges)
}

private actor DraftWriteGate {
    private var started = false
    private var waitingForStart: CheckedContinuation<Void, Never>?
    private var releaseFirst: CheckedContinuation<Void, Never>?
    private(set) var snapshots: [DraftSnapshot] = []
    func write(_ snapshot: DraftSnapshot, to file: URL) async throws {
        snapshots.append(snapshot)
        if snapshots.count == 1 {
            await withCheckedContinuation { continuation in
                releaseFirst = continuation; started = true
                waitingForStart?.resume(); waitingForStart = nil
            }
        }
        try LocalFiles.write(snapshot, to: file)
    }
    func waitForStart() async {
        if started { return }
        await withCheckedContinuation { waitingForStart = $0 }
    }
    func release() { releaseFirst?.resume(); releaseFirst = nil }
}

@Test @MainActor func draftWritesDoNotBlockEditingAndCoalesceWithoutRestoringOldText() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let gate = DraftWriteGate()
    let file = directory.appendingPathComponent("drafts.json")
    let store = DraftStore(file: file, write: { try await gate.write($0, to: $1) }, report: { _, _ in Issue.record("Unexpected save failure") })
    await store.load(scope: "a")
    store.texts["thread"] = "old"; store.save()
    await gate.waitForStart()
    // Editing and queuing remain possible while disk I/O is suspended.
    store.texts["thread"] = "intermediate"; store.save()
    store.texts["thread"] = "newest"; store.images["thread"] = ["image"]; store.save()
    store.reset()
    await gate.release()
    #expect(await store.flush())
    #expect(await gate.snapshots.count == 2)
    let restored = DraftStore(file: file, report: { _, _ in Issue.record("Unexpected read failure") })
    await restored.load(scope: "b")
    #expect(restored.texts.isEmpty)
    await restored.load(scope: "a")
    #expect(restored.texts["thread"] == "newest")
    #expect(restored.images["thread"] == ["image"])
    restored.texts["thread"] = ""; restored.images["thread"] = []
    #expect(await restored.flush())
    await restored.load(scope: "a")
    #expect(restored.texts.isEmpty && restored.images.isEmpty)
}
