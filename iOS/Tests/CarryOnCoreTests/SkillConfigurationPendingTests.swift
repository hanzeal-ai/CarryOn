import Foundation
import Testing
@testable import CarryOnCore

@MainActor @Test func pendingSkillConfigurationRequiresExactPathStateAndConfirmedInventory() throws {
    let suite = "skill-config-pending-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    let pending = PendingWrites(defaults: defaults), body: JSONValue = .object(["path": .string("/skills/fixture/SKILL.md"), "enabled": .bool(false)])
    let id = try pending.requestID(scope: "scope", target: "skill-config", path: "/api/threads/thread/skills/config", body: body)
    let restored = PendingWrites(defaults: defaults)
    let job: JSONValue = .object(["id": .string(id), "threadId": .string("thread"), "kind": .string("skill-config"), "body": body, "state": .string("completed"), "result": body.setting("threadId", .string("thread"))])
    for state in ["failed", "completed"] {
        try restored.reconcile(scope: "scope", job: job.setting("state", .string(state)).setting("body", body.setting("enabled", .bool(true))))
        #expect(restored.hasPending(scope: "scope", target: "skill-config"))
    }
    try restored.reconcile(scope: "scope", job: job.setting("result", job["result"].setting("path", .string("/other"))))
    #expect(restored.hasPending(scope: "scope", target: "skill-config"))
    try restored.reconcile(scope: "scope", job: job)
    #expect(!restored.hasPending(scope: "scope", target: "skill-config"))
    #expect(WorkspaceCapability.request(path: "/api/threads/thread/skills/config", body: body) == [.edit])
}
