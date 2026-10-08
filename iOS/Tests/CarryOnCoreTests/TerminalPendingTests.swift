import Foundation
import Testing
@testable import CarryOnCore

@MainActor @Test func pendingTerminalRequiresOriginalBodyAndNativeConfirmation() throws {
    let suite = "terminal-pending-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    for action in ["terminate", "clean"] {
        let pending = PendingWrites(defaults: defaults)
        let body: JSONValue = .object(action == "clean" ? ["action": .string(action)] : ["action": .string(action), "processId": .string("native-pid")])
        let id = try pending.requestID(scope: "scope", target: "terminal:thread", path: "/api/threads/thread/terminals", body: body)
        let restored = PendingWrites(defaults: defaults)
        let result: JSONValue = .object(action == "clean" ? ["threadId": .string("thread"), "cleaned": .bool(true)] : ["threadId": .string("thread"), "processId": .string("native-pid"), "terminated": .bool(true)])
        let job: JSONValue = .object(["id": .string(id), "threadId": .string("thread"), "kind": .string("terminal-" + action), "body": body, "state": .string("completed"), "result": result])
        for state in ["completed", "failed"] {
            try restored.reconcile(scope: "scope", job: job.setting("state", .string(state)).setting("body", .object(["action": .string("terminate"), "processId": .string("wrong")])))
            #expect(restored.hasPending(scope: "scope", target: "terminal:thread"))
        }
        try restored.reconcile(scope: "scope", job: job.setting("result", result.setting("threadId", .string("wrong"))))
        #expect(restored.hasPending(scope: "scope", target: "terminal:thread"))
        try restored.reconcile(scope: "other", job: job)
        #expect(restored.hasPending(scope: "scope", target: "terminal:thread"))
        try restored.reconcile(scope: "scope", job: job)
        #expect(!restored.hasPending(scope: "scope", target: "terminal:thread"))
    }
}
@Test func terminalStopPermissionIsDistinctFromSendAndRead() {
    #expect(WorkspaceCapability.request(path: "/api/threads/thread/terminals") == [.view])
    #expect(WorkspaceCapability.request(path: "/api/threads/thread/terminals", body: .object(["action": .string("clean")])) == [.stop])
}
