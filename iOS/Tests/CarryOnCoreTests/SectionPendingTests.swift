import Foundation
import Testing
@testable import CarryOnCore

@MainActor @Test func pendingSectionMovePreservesDestinationAndExplicitNullConfirmation() throws {
    let suite = "section-pending-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    for destination in [JSONValue.null, .string("pinned")] {
        let pending = PendingWrites(defaults: defaults)
        let body = JSONValue.object(["sectionId": destination])
        let id = try pending.requestID(scope: "scope", target: "thread", path: "/api/threads/thread/section", body: body)
        let restored = PendingWrites(defaults: defaults)
        let job = JSONValue.object(["id": .string(id), "threadId": .string("thread"), "kind": .string("section-move"),
            "sectionId": destination, "state": .string("completed"), "result": .object(["threadId": .string("thread"), "sectionId": destination])])
        try restored.reconcile(scope: "scope", job: job.setting("result", .object(["threadId": .string("thread")])))
        #expect(restored.hasPending(scope: "scope", target: "thread"))
        for state in ["completed", "failed"] {
            try restored.reconcile(scope: "scope", job: job.setting("state", .string(state)).setting("sectionId", .string("wrong")))
            #expect(restored.hasPending(scope: "scope", target: "thread"))
        }
        try restored.reconcile(scope: "other", job: job)
        #expect(restored.hasPending(scope: "scope", target: "thread"))
        try restored.reconcile(scope: "scope", job: job)
        #expect(!restored.hasPending(scope: "scope", target: "thread"))
    }
}

@MainActor @Test func pendingSectionManagementRequiresExactBodyAndCanonicalResultAfterRestore() throws {
    let suite = "section-management-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    for action in ["create", "update", "delete"] {
        let pending = PendingWrites(defaults: defaults)
        let body: JSONValue = .object(action == "create" ? ["name": .string("研发")] : action == "update" ? ["action": .string(action), "name": .string("研发")] : ["action": .string(action)])
        let path = action == "create" ? "/api/sections" : "/api/sections/group"
        let id = try pending.requestID(scope: "scope", target: "sections", path: path, body: body)
        let restored = PendingWrites(defaults: defaults)
        let job = JSONValue.object(["id": .string(id), "kind": .string("section-" + action), "threadId": .string(action == "create" ? "sections" : "group"), "sectionId": action == "create" ? .null : .string("group"), "body": body, "state": .string("completed"), "result": action == "delete" ? .object(["sectionId": .string("group"), "deleted": .bool(true)]) : .object(["section": .object(["id": .string("group"), "name": .string("研发")])])])
        try restored.reconcile(scope: "scope", job: job.setting("result", .object([:])))
        #expect(restored.hasPending(scope: "scope", target: "sections"))
        for state in ["failed", "completed"] {
            try restored.reconcile(scope: "scope", job: job.setting("state", .string(state)).setting("body", body.setting("name", .string("错误名称"))))
            #expect(restored.hasPending(scope: "scope", target: "sections"))
        }
        try restored.reconcile(scope: "other", job: job)
        #expect(restored.hasPending(scope: "scope", target: "sections"))
        try restored.reconcile(scope: "scope", job: job)
        #expect(!restored.hasPending(scope: "scope", target: "sections"))
    }
}

@MainActor @Test func pendingSectionOrderRequiresCanonicalAdjacentPositionAndExplicitNull() throws {
    let suite = "section-order-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    for before in [JSONValue.null, .string("next")] {
        let pending = PendingWrites(defaults: defaults)
        let body = JSONValue.object(["action": .string("order"), "threadId": .string("thread"), "beforeThreadId": before])
        let id = try pending.requestID(scope: "scope", target: "sections", path: "/api/sections/group", body: body)
        let result = JSONValue.object(["threadId": .string("thread"), "sectionId": .string("group"), "beforeThreadId": before])
        let job = JSONValue.object(["id": .string(id), "kind": .string("section-order"), "threadId": .string("thread"), "sectionId": .string("group"), "body": body, "state": .string("completed"), "result": result])
        for wrong in [result.setting("beforeThreadId", .string("wrong")), result.setting("sectionId", .string("wrong")), .object(["threadId": .string("thread"), "sectionId": .string("group")])] {
            try pending.reconcile(scope: "scope", job: job.setting("result", wrong))
            #expect(pending.hasPending(scope: "scope", target: "sections"))
        }
        try pending.reconcile(scope: "scope", job: job)
        #expect(!pending.hasPending(scope: "scope", target: "sections"))
    }
}
