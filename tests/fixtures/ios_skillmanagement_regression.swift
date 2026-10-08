import SwiftUI
import CarryOnCore
import UIKit

final class SkillTransport: URLProtocol, @unchecked Sendable {
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
            if path == "/api/threads/fixture/skills/config" {
                writes += 1; let id = body["requestId"] as! String
                jobs[id] = ["id": id, "threadId": "fixture", "kind": "skill-config", "body": ["path": body["path"]!, "enabled": body["enabled"]!], "state": "completed", "result": ["threadId": "fixture", "path": body["path"]!, "enabled": body["enabled"]!]]
                return ["id": "wrong", "state": "failed"]
            }
            if path == "/api/threads/fixture/skills" { return ["skills": [["name": "review", "path": "/skills/review/SKILL.md", "description": "检查实现与协议的一致性", "enabled": true], ["name": "frontend", "path": "/skills/frontend/SKILL.md", "description": "构建可验证的界面与交互", "enabled": false]], "errors": []] }
            if path.hasPrefix("/api/jobs/") { queries += 1; let id = String(path.split(separator: "/").last!); var job = jobs[id] ?? [:]; if queries == 3 { job["state"] = "failed"; job["error"] = "fixture native config rejected" }; if queries == 1 { job["body"] = ["path": "/wrong", "enabled": false]; job["state"] = "failed" }; return job }
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

@MainActor struct SkillRegression: View {
    @State private var model = AppModel()
    @State private var show = false
    @State private var started = false
    @State private var scope = ""
    @State private var presentation = 0
    @State private var snapshot: [String: Any] = [:]
    private let thread = try! Record(.object(["id": .string("fixture"), "title": .string("后台任务")]))
    var body: some View {
        Color.clear.environment(model).sheet(isPresented: $show) { SkillManagementView(thread: thread, scope: model.scope).id(presentation).environment(model) }
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.skills.snapshot"))) { snapshot = $0.object as? [String: Any] ?? [:] }
            .task { await run() }
    }
    func wait() async { try? await Task.sleep(for: .milliseconds(650)) }
    func inspect() { NotificationCenter.default.post(name: .init("fixture.skills.inspect"), object: nil) }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [SkillTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://skills-fixture.invalid/"), configuration: config))
        model.addressText = "https://skills-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "edit"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true; model.selectedThread = thread
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.history = .object(["thread": thread.value, "status": .object(["state": .string("idle")]), "access": .object(["canInteract": .bool(true)]), "controls": .object(["supportsSkills": .bool(true)])])
        scope = model.scope
        for id in (try? model.pending.requestIDs(scope: scope, target: "skill-config")) ?? [] { try? model.pending.resolve(scope: scope, target: "skill-config", requestID: id) }
        model.draft = "保留草稿"; show = true; await wait(); inspect()
        let loaded = snapshot["loaded"] as? Bool == true && snapshot["rows"] as? Int == 2
        if let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first { let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }; try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("skillmanagement.png")) }
        model.history = model.history.setting("access", .object(["canInteract": .bool(false)]))
        NotificationCenter.default.post(name: .init("fixture.skills.stop"), object: "/skills/review/SKILL.md"); await wait()
        let readOnlyBlocks = SkillTransport.store.counts().0 == 0
        model.history = model.history.setting("access", .object(["canInteract": .bool(true), "nativeReady": .bool(false)]))
        NotificationCenter.default.post(name: .init("fixture.skills.stop"), object: "/skills/review/SKILL.md"); await wait()
        let unreadyBlocks = SkillTransport.store.counts().0 == 0
        model.history = model.history.setting("access", .object(["canInteract": .bool(true), "nativeReady": .bool(true)])).setting("controls", .object(["supportsSkills": .bool(false)]))
        NotificationCenter.default.post(name: .init("fixture.skills.stop"), object: "/skills/review/SKILL.md"); await wait()
        let capabilityBlocks = SkillTransport.store.counts().0 == 0
        model.history = model.history.setting("controls", .object(["supportsSkills": .bool(true)]))
        NotificationCenter.default.post(name: .init("fixture.skills.stop"), object: "/skills/review/SKILL.md"); await wait()
        let unknownRetained = model.pending.hasPending(scope: scope, target: "skill-config") && SkillTransport.store.counts().0 == 1
        show = false; await wait(); presentation += 1; show = true; await wait()
        let wrongRestoreRetained = model.pending.hasPending(scope: scope, target: "skill-config") && SkillTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.skills.stop"), object: "/skills/frontend/SKILL.md"); await wait()
        let noReplay = SkillTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.skills.check"), object: nil); await wait()
        let confirmed = !model.pending.hasPending(scope: scope, target: "skill-config") && SkillTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.skills.stop"), object: "/skills/frontend/SKILL.md"); await wait()
        NotificationCenter.default.post(name: .init("fixture.skills.check"), object: nil); await wait(); inspect()
        let failedVisible = snapshot["failure"] as? String == "fixture native config rejected" && !model.pending.hasPending(scope: scope, target: "skill-config")
        let draft = model.draft == "保留草稿"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array([])]))]; await wait(); inspect()
        let revoked = snapshot["rows"] as? Int == 0 && !show
        let checks = ["readOnlyBlocks": readOnlyBlocks, "unreadyBlocks": unreadyBlocks, "capabilityBlocks": capabilityBlocks, "failedWriteRemainsVisible": failedVisible, "loadedNativeInventory": loaded, "unknownRetained": unknownRetained, "wrongRestoreRetained": wrongRestoreRetained, "noReplay": noReplay, "canonicalConfirmed": confirmed, "draftPreserved": draft, "revokeClearsRows": revoked]
        try? JSONSerialization.data(withJSONObject: ["passed": checks.values.allSatisfy { $0 }, "checks": checks, "diagnostic": snapshot]).write(to: URL.documentsDirectory.appendingPathComponent("skillmanagement-result.json"))
    }
}
@main struct CarryOnApp: App { var body: some Scene { WindowGroup { SkillRegression() } } }
