import SwiftUI
import CarryOnCore
import UIKit

final class TerminalTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        private let lock = NSLock()
        private var writes = 0
        private var queries = 0
        private var jobs: [String: [String: Any]] = [:]
        func counts() -> (Int, Int) { lock.lock(); defer { lock.unlock() }; return (writes, queries) }
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? "", body = envelope["body"] as? [String: Any] ?? [:]
            if path.hasPrefix("/api/threads/fixture/terminals") {
                if envelope["method"] as? String == "POST" {
                    writes += 1; let id = body["requestId"] as! String
                    jobs[id] = ["id": id, "threadId": "fixture", "kind": "terminal-terminate", "body": ["action": "terminate", "processId": body["processId"]!], "state": "completed", "result": ["threadId": "fixture", "processId": body["processId"]!, "terminated": true]]
                    return ["id": "wrong", "state": "failed"]
                }
                return ["threadId": "fixture", "terminals": [["id": "native-1", "processId": "native-1", "command": "npm run dev -- --host 127.0.0.1", "cwd": "/workspace/CarryOn"], ["id": "native-2", "processId": "native-2", "command": "python3 scripts/check_long_running_background_task.py", "cwd": "/workspace/CarryOn/a/long/path/to/a/project"]], "nextCursor": NSNull()]
            }
            if path.hasPrefix("/api/jobs/") { queries += 1; let id = String(path.split(separator: "/").last!); var job = jobs[id] ?? [:]; if queries == 3 { job["state"] = "failed"; job["error"] = "fixture native stop rejected" }; if queries == 1 { job["body"] = ["action": "terminate", "processId": "wrong"]; job["state"] = "failed" }; return job }
            return [:]
        }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; bytes.append(buffer, count: n) }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: Self.store.respond(envelope))); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor struct TerminalRegression: View {
    @State private var model = AppModel()
    @State private var show = false
    @State private var started = false
    @State private var scope = ""
    @State private var presentation = 0
    @State private var snapshot: [String: Any] = [:]
    private let thread = try! Record(.object(["id": .string("fixture"), "title": .string("后台任务")]))
    var body: some View {
        Color.clear.environment(model).sheet(isPresented: $show) { BackgroundTerminalsView(thread: thread, scope: model.scope).id(presentation).environment(model) }
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.terminals.snapshot"))) { snapshot = $0.object as? [String: Any] ?? [:] }
            .task { await run() }
    }
    func wait() async { try? await Task.sleep(for: .milliseconds(650)) }
    func inspect() { NotificationCenter.default.post(name: .init("fixture.terminals.inspect"), object: nil) }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [TerminalTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://terminals-fixture.invalid/"), configuration: config))
        model.addressText = "https://terminals-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "stop"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true; model.selectedThread = thread
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.history = .object(["thread": thread.value, "status": .object(["state": .string("idle")]), "access": .object(["canInteract": .bool(true)]), "controls": .object(["supportsBackgroundTerminals": .bool(true)])])
        scope = model.scope
        for id in (try? model.pending.requestIDs(scope: scope, target: "terminal:fixture")) ?? [] { try? model.pending.resolve(scope: scope, target: "terminal:fixture", requestID: id) }
        model.draft = "保留草稿"; show = true; await wait(); inspect()
        let loaded = snapshot["loaded"] as? Bool == true && snapshot["rows"] as? Int == 2
        if let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first { let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }; try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("terminals.png")) }
        model.history = model.history.setting("access", .object(["canInteract": .bool(false)]))
        NotificationCenter.default.post(name: .init("fixture.terminals.stop"), object: "native-1"); await wait()
        let readOnlyBlocks = TerminalTransport.store.counts().0 == 0
        model.history = model.history.setting("access", .object(["canInteract": .bool(true), "nativeReady": .bool(false)]))
        NotificationCenter.default.post(name: .init("fixture.terminals.stop"), object: "native-1"); await wait()
        let unreadyBlocks = TerminalTransport.store.counts().0 == 0
        model.history = model.history.setting("access", .object(["canInteract": .bool(true), "nativeReady": .bool(true)])).setting("controls", .object(["supportsBackgroundTerminals": .bool(false)]))
        NotificationCenter.default.post(name: .init("fixture.terminals.stop"), object: "native-1"); await wait()
        let capabilityBlocks = TerminalTransport.store.counts().0 == 0
        model.history = model.history.setting("controls", .object(["supportsBackgroundTerminals": .bool(true)]))
        NotificationCenter.default.post(name: .init("fixture.terminals.stop"), object: "native-1"); await wait()
        let unknownRetained = model.pending.hasPending(scope: scope, target: "terminal:fixture") && TerminalTransport.store.counts().0 == 1
        show = false; await wait(); presentation += 1; show = true; await wait()
        let wrongRestoreRetained = model.pending.hasPending(scope: scope, target: "terminal:fixture") && TerminalTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.terminals.stop"), object: "native-2"); await wait()
        let noReplay = TerminalTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.terminals.check"), object: nil); await wait()
        let confirmed = !model.pending.hasPending(scope: scope, target: "terminal:fixture") && TerminalTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.terminals.stop"), object: "native-2"); await wait()
        NotificationCenter.default.post(name: .init("fixture.terminals.check"), object: nil); await wait(); inspect()
        let failedVisible = snapshot["failure"] as? String == "fixture native stop rejected" && !model.pending.hasPending(scope: scope, target: "terminal:fixture")
        let draft = model.draft == "保留草稿"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array([])]))]; await wait(); inspect()
        let revoked = snapshot["rows"] as? Int == 0 && !show
        let checks = ["readOnlyBlocks": readOnlyBlocks, "unreadyBlocks": unreadyBlocks, "capabilityBlocks": capabilityBlocks, "failedWriteRemainsVisible": failedVisible, "loadedNativeInventory": loaded, "unknownRetained": unknownRetained, "wrongRestoreRetained": wrongRestoreRetained, "noReplay": noReplay, "canonicalConfirmed": confirmed, "draftPreserved": draft, "revokeClearsRows": revoked]
        try? JSONSerialization.data(withJSONObject: ["passed": checks.values.allSatisfy { $0 }, "checks": checks, "diagnostic": snapshot]).write(to: URL.documentsDirectory.appendingPathComponent("terminals-result.json"))
    }
}
@main struct CarryOnApp: App { var body: some Scene { WindowGroup { TerminalRegression() } } }
