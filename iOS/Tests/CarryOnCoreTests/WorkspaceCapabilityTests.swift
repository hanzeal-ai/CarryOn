import Testing
@testable import CarryOnCore

@Test func workspaceGrantsFailClosedAndSeparateCapabilities() {
    for value: JSONValue in [.null, .object([:]), .array([]), .array([.string("send")])] {
        #expect(!WorkspaceCapability.send.isGranted(in: value))
    }
    let stopOnly: JSONValue = .array([.string("view"), .string("stop")])
    #expect(WorkspaceCapability.stop.isGranted(in: stopOnly))
    #expect(!WorkspaceCapability.send.isGranted(in: stopOnly))
    #expect(!WorkspaceCapability.approve.isGranted(in: stopOnly))
    for capability in WorkspaceCapability.allCases {
        let grants: JSONValue = .array([.string("view"), .string(capability.rawValue)])
        #expect(capability.isGranted(in: grants))
    }
}

@Test func workspaceRequestPermissionsMatchConsoleContract() {
    let operations: [(WorkspaceCapability, [String])] = [
        (.stop, ["interrupt"]), (.send, ["steer", "resume", "queue-add", "queue-resume"]),
        (.edit, ["edit", "compact", "settings", "queue-edit", "queue-delete", "queue-reorder", "clear-queue"]),
        (.approve, ["command-approval", "file-approval", "permissions-approval", "user-input", "mcp-response"])
    ]
    for (capability, actions) in operations {
        for action in actions {
            for prefix in ["/api/threads/t", "/api/side-chats/s"] {
                #expect(WorkspaceCapability.request(path: prefix + "/operations", body: .object(["action": .string(action)])) == capability)
            }
        }
    }
    #expect(WorkspaceCapability.request(path: "/api/threads", body: .object([:])) == .create)
    #expect(WorkspaceCapability.request(path: "/api/threads/t/compose", body: .object([:])) == .send)
    #expect(WorkspaceCapability.request(path: "/api/jobs/j/acknowledge", body: .object([:])) == .send)
    #expect(WorkspaceCapability.request(path: "/api/streams/s/read", body: .object([:])) == .view)
    #expect(WorkspaceCapability.request(path: "/api/notifications/token", body: .object([:])) == .view)
    #expect(WorkspaceCapability.request(path: "/api/threads/t/history") == .view)
    #expect(WorkspaceCapability.request(path: "/api/threads/t/images/i?parentId=p") == .files)
    #expect(WorkspaceCapability.request(path: "/api/side-chats/t/artifacts/a") == .files)
    #expect(WorkspaceCapability.request(path: "/api/threads/t/operations", body: .object(["action": .string("unknown")])) == nil)
    #expect(WorkspaceCapability.request(path: "/api/unknown", body: .object([:])) == nil)
}
