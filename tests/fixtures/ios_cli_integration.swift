import SwiftUI
import CarryOnCore

@main struct CLIIntegrationApp: App {
    @State private var fixture = CLIIntegrationFixture()
    var body: some Scene {
        WindowGroup { RootView().environment(fixture.model).sheet(isPresented: $fixture.showConnections) { WorkspaceSwitcher().environment(fixture.model) }.task { await fixture.run() } }
    }
}

@MainActor @Observable final class CLIIntegrationFixture {
    var model = AppModel()
    var showConnections = false
    private var started = false
    private var checks: [String: Bool] = [:]
    private var tid = ""
    func expect(_ name: String, _ condition: Bool) throws {
        checks[name] = condition
        if !condition { throw APIError("Failed: " + name + " / " + (model.error ?? "")) }
    }
    func until(_ name: String, _ condition: () -> Bool) async throws {
        for _ in 0..<600 {
            if condition() { checks[name] = true; return }
            try await Task.sleep(for: .milliseconds(50))
        }
        throw APIError("Timeout: " + name + " / " + (model.error ?? model.historyFailure ?? ""))
    }
    func step(_ name: String) async throws {
        _ = try await model.console("fixture/" + name, body: .object([:]))
    }
    var text: String { model.history["timeline"].array.map { $0["text"].text }.joined(separator: "\n") }
    var idle: Bool { model.history["status"]["state"].text == "idle" }
    func send(_ tag: String) async throws {
        let target = ConversationActionTarget(scope: model.scope, threadID: tid)
        let ok = await model.write(path: target.path("compose"), target: tid, body: target.body(["prompt": .string(tag)]))
        try expect("phone sends " + tag, ok)
    }
    func screenshot(_ name: String) throws {
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) else { throw APIError("No window") }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent(name + ".png"))
    }
    func run() async {
        guard !started else { return }; started = true
        do {
            let config = try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: URL.documentsDirectory.appendingPathComponent("cli-config.json")))
            await model.restoreLogin()
            model.addressText = config["url"].text; model.username = "test-owner"; model.credential = config["password"].text
            await model.login()
            try expect("authenticated over HTTPS", model.authenticated)
            let grouped = config["workspaceConnections"].bool == true
            let shared = config["sharedBinding"].bool == true
            let cliDeviceID = config["cliDeviceId"].string ?? "cli-fixture"
            if model.selectedDevice != cliDeviceID { model.switchDevice(cliDeviceID) }
            if grouped {
                try expect("one workspace two connections", model.workspaceGroups.count == 1 && model.workspaceGroups[0].connections.count == 2)
                try expect("connection labels", Set(model.workspaceGroups[0].connections.map(WorkspaceGroup.connectionLabel)) == Set(["桌面端", "CLI"]))
                showConnections = true
                try await Task.sleep(for: .milliseconds(900))
                try screenshot("cli-workspace-connections")
                showConnections = false
            }
            tid = config["threadId"].text
            let rows = try await model.deviceRequest("/api/threads")["threads"].array
            guard let row = rows.first(where: { $0["id"].text == tid }) else { throw APIError("CLI session not discovered") }
            checks["discovers CLI session"] = true
            model.open(try Record(row))
            try await until("history and controls synchronized", { model.historySynchronized && model.canWrite && self.idle })
            try expect("CLI backend identity", model.status["backend"].text == "codex-cli")

            try await step("cli-stream")
            try await until("CLI live delta before completion", { self.text.contains("CLI_STREAM_ALPHA_") && self.model.history["status"]["state"].text == "running" })
            try screenshot("cli-stream")
            if grouped {
                model.switchDevice("desktop-fixture")
                try expect("switch clears CLI history and controls", model.history == .null && !model.canInteract)
                model.open(try Record(row))
                try await until("desktop fixture independently synchronized", { self.model.historySynchronized })
                try expect("same thread different connection history", !self.text.contains("CLI_STREAM_ALPHA_") && model.history["controls"]["requests"].array.isEmpty)
                if shared {
                    try expect("confirmed workspace grants shared", model.allows(.approve))
                    try expect("per-connection local read-only gate preserved", !model.canWrite)
                } else { try expect("CLI grant not inherited by desktop", !model.allows(.approve) && !model.canWrite) }
            }
            try await step("release-cli-stream")
            if grouped { model.switchDevice(cliDeviceID); model.open(try Record(row)) }
            try await until("CLI stream completed", { self.model.historySynchronized && self.idle && self.text.contains("CLI_STREAM_ALPHA_\nOMEGA") })
            try await send("CARRYON_STREAM")
            try await until("phone live delta before completion", { self.text.contains("CARRYON_STREAM_ALPHA_") && !self.idle })
            try await step("verify-phone-stream")
            try await until("phone stream completed", { self.idle })

            try await step("cli-approval")
            try await until("CLI approval on phone", { !self.model.history["controls"]["requests"].array.isEmpty })
            let request = model.history["controls"]["requests"].array[0]
            try screenshot("cli-approval")
            if grouped {
                let cliTarget = ConversationActionTarget(scope: model.scope, threadID: tid)
                model.switchDevice("desktop-fixture"); model.open(try Record(row))
                try await until("desktop while CLI approval waits", { self.model.historySynchronized })
                try expect("pending approval stays on origin", model.history["controls"]["requests"].array.isEmpty)
                let misrouted = await model.perform("command-approval", target: cliTarget, fields: ["nativeRequestId": request["id"], "requestFingerprint": request["fingerprint"], "decision": .string("accept")])
                try expect("stale approval target refused after switch", !misrouted)
                model.switchDevice(cliDeviceID); model.open(try Record(row))
                try await until("original approval restored on switch back", { self.model.historySynchronized && self.model.history["controls"]["requests"].array.first?["fingerprint"] == request["fingerprint"] })
            }
            let accepted = await model.perform("command-approval", target: .init(scope: model.scope, threadID: tid), fields: ["nativeRequestId": request["id"], "requestFingerprint": request["fingerprint"], "decision": .string("accept")])
            try expect("phone approves CLI command", accepted)
            try await until("approval resolved on phone", { self.idle && self.model.history["controls"]["requests"].array.isEmpty })
            try await step("verify-phone-approval")

            try await send("APPROVAL_CLI")
            try await until("phone command awaits CLI approval", { !self.model.history["controls"]["requests"].array.isEmpty })
            try await step("approve-in-cli")
            try await until("CLI approval clears phone request", { self.idle && self.model.history["controls"]["requests"].array.isEmpty })

            try await send("DISCONNECT_CARRYON")
            try await until("running before native disconnect", { self.text.contains("DISCONNECT_CARRYON_ALPHA_") && !self.idle })
            try await step("native-disconnect")
            try await until("native reconnect restores completed turn", { self.idle && self.text.contains("DISCONNECT_CARRYON_ALPHA_\nOMEGA") && self.model.canWrite })

            try await send("LATE_APPROVAL")
            try await until("pending before native disconnect", { !self.model.history["controls"]["requests"].array.isEmpty })
            let original = model.history["controls"]["requests"].array[0]["id"]
            try await step("pending-reconnect")
            try await until("pending approval restored", { self.model.canWrite && self.model.history["controls"]["requests"].array.first?["id"] == original })
            let restored = model.history["controls"]["requests"].array[0]
            let approved = await model.perform("command-approval", target: .init(scope: model.scope, threadID: tid), fields: ["nativeRequestId": restored["id"], "requestFingerprint": restored["fingerprint"], "decision": .string("accept")])
            try expect("approve after reconnect", approved)
            try await until("recovered approval completes", { self.idle })

            try await step("cli-disconnect")
            try await until("CLI exit preserves turn", { self.idle && self.text.contains("DISCONNECT_CLI_ALPHA_\nOMEGA") })
            model.setForeground(false); model.expireBackgroundSync()
            try await step("phone-disconnect")
            model.setForeground(true)
            try await until("phone reconnect restores missed history", { self.model.historySynchronized && self.text.contains("RECONNECT_ALPHA_\nOMEGA") })
            try screenshot("cli-recovered")
            if shared {
                try await model.removeDevice("desktop-fixture")
                try await until("remaining CLI connection stays authorized", { self.model.historySynchronized && self.model.canInteract })
                try expect("removing original connection preserves workspace", model.workspaceGroups.count == 1 && model.workspaceGroups[0].connections.count == 1 && model.allows(.approve))
            }
            try await step("verify-final")
            try save(passed: true)
        } catch { try? save(passed: false, error: String(describing: error)) }
    }
    func save(passed: Bool, error: String = "") throws {
        try JSONEncoder().encode(model.history).write(to: URL.documentsDirectory.appendingPathComponent("cli-history.json"))
        try JSONSerialization.data(withJSONObject: ["passed": passed, "checks": checks, "error": error], options: [.prettyPrinted, .sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("cli-result.json"))
    }
}
