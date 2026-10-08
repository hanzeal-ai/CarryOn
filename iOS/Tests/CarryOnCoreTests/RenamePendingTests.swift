import Foundation
import Testing
@testable import CarryOnCore

@MainActor @Test func pendingRenameRestoresExactIDsAndRequiresCanonicalName() throws {
    let suite = "rename-pending-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    let pending = PendingWrites(defaults: defaults)
    let body = JSONValue.object(["name": .string("名称 🧭")])
    let id = try pending.requestID(scope: "scope", target: "thread", path: "/api/threads/thread/rename", body: body)
    let restored = PendingWrites(defaults: defaults)
    #expect(try restored.requestIDs(scope: "scope", target: "thread") == [id])
    #expect(try restored.requestIDs(scope: "other", target: "thread").isEmpty)
    #expect(try restored.requestIDs(scope: "scope", target: "other").isEmpty)
    let job = JSONValue.object(["id": .string(id), "threadId": .string("thread"), "kind": .string("rename"),
        "name": .string("名称 🧭"), "state": .string("completed"),
        "result": .object(["threadId": .string("thread"), "name": .string("旧名称")])])
    try restored.reconcile(scope: "scope", job: job)
    #expect(restored.hasPending(scope: "scope", target: "thread"))
    for state in ["completed", "failed"] {
        try restored.reconcile(scope: "scope", job: job.setting("state", .string(state)).setting("name", .string("wrong"))
            .setting("result", .object(["threadId": .string("thread"), "name": .string("wrong")])))
        #expect(restored.hasPending(scope: "scope", target: "thread"))
    }
    try restored.reconcile(scope: "scope", job: job.setting("result", .object(["threadId": .string("thread"), "name": body["name"]])))
    #expect(!restored.hasPending(scope: "scope", target: "thread"))
}
