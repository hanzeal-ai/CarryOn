import Foundation
import Testing
@testable import CarryOnCore

@MainActor @Test func pendingPluginRequiresOriginalIdentityAndNativeInstalledState() throws {
    let suite = "plugin-pending-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    for action in ["install", "uninstall"] {
        let pending = PendingWrites(defaults: defaults), body: JSONValue = .object(["action": .string(action), "pluginId": .string("fixture@market")])
        let id = try pending.requestID(scope: "scope", target: "plugin-management", path: "/api/threads/thread/plugins", body: body)
        let restored = PendingWrites(defaults: defaults)
        let result: JSONValue = .object(["threadId": .string("thread"), "pluginId": .string("fixture@market"), "installed": .bool(action == "install"), "appsNeedingAuth": .null])
        let job: JSONValue = .object(["id": .string(id), "threadId": .string("thread"), "kind": .string("plugin-" + action), "body": body, "state": .string("completed"), "result": result])
        for state in ["failed", "completed"] {
            try restored.reconcile(scope: "scope", job: job.setting("state", .string(state)).setting("body", body.setting("pluginId", .string("wrong"))))
            #expect(restored.hasPending(scope: "scope", target: "plugin-management"))
        }
        try restored.reconcile(scope: "scope", job: job.setting("result", result.setting("installed", .bool(action != "install"))))
        #expect(restored.hasPending(scope: "scope", target: "plugin-management"))
        try restored.reconcile(scope: "scope", job: job)
        #expect(!restored.hasPending(scope: "scope", target: "plugin-management"))
    }
    #expect(WorkspaceCapability.request(path: "/api/threads/thread/plugins", body: .object(["action": .string("install")])) == [.edit])
}

@MainActor @Test func discoveryPluginKeepsOriginalScopeAndOpaquePageIdentity() throws {
    let suite = "plugin-discovery-" + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite)); defer { defaults.removePersistentDomain(forName: suite) }
    let discovery: JSONValue = .object(["searchTerm": .string("fixture"), "scope": .string("global"), "cursor": .string("opaque/+=")])
    let body: JSONValue = .object(["action": .string("install"), "pluginId": .string("remote@market"), "discovery": discovery])
    let pending = PendingWrites(defaults: defaults)
    let id = try pending.requestID(scope: "scope", target: "plugin-management", path: "/api/threads/thread/plugins", body: body)
    let restored = PendingWrites(defaults: defaults)
    let job: JSONValue = .object(["id": .string(id), "threadId": .string("thread"), "kind": .string("plugin-install"), "body": body, "state": .string("completed"), "result": .object(["threadId": .string("thread"), "pluginId": .string("remote@market"), "installed": .bool(true)])])
    #expect(try PluginReceipt(job).body == body)
    for changed in [discovery.setting("scope", .string("personal")), discovery.setting("cursor", .null)] {
        try restored.reconcile(scope: "scope", job: job.setting("body", body.setting("discovery", changed)))
        #expect(restored.hasPending(scope: "scope", target: "plugin-management"))
    }
    try restored.reconcile(scope: "scope", job: job)
    #expect(!restored.hasPending(scope: "scope", target: "plugin-management"))
}
