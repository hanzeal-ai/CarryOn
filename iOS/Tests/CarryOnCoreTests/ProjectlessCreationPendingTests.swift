import Foundation
import Testing
@testable import CarryOnCore

@Test @MainActor func projectlessCreationReceiptReconcilesAfterRestart() throws {
    for terminal in ["failed", "completed"] {
        let suite = "projectless-create-" + UUID().uuidString
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let pending = PendingWrites(defaults: defaults)
        let body: JSONValue = .object(["prompt": .string("hello")])
        let id = try pending.requestID(scope: "scope", target: "new:", path: "/api/threads", body: body)
        let restored = PendingWrites(defaults: defaults)
        let receipt: JSONValue = .object(["id": .string(id), "threadId": .string("created-thread"),
            "kind": .string("create"), "state": .string("uncertain"), "creationProject": .null])
        try restored.reconcile(scope: "scope", job: receipt)
        #expect(try restored.requestID(scope: "scope", target: "new:", path: "/api/threads", body: body) == id)
        try restored.reconcile(scope: "scope", job: receipt.setting("state", .string("completed")))
        #expect(restored.hasPending(scope: "scope", target: "new:"))
        try restored.reconcile(scope: "scope", job: receipt.setting("state", .string(terminal)).setting("createdThreadId", .string("created-thread")))
        #expect(!restored.hasPending(scope: "scope", target: "new:"))
        #expect(try restored.requestID(scope: "scope", target: "new:", path: "/api/threads", body: body) != id)
    }
}
