import SwiftUI
import CarryOnCore

@main struct RenameRegressionApp: App {
    @State private var fixture = RenameFixture()
    var body: some Scene { WindowGroup {
        Text("重命名回归").overlay {
            if fixture.show { RenameConversationView(thread: fixture.thread, scope: fixture.scope).id(fixture.presentation) }
        }.environment(fixture.model).task { await fixture.run() }
    } }
}
private final class RenameTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock(); var writes = 0, queries = 0, jobs: [String: [String: Any]] = [:]
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? "", body = envelope["body"] as? [String: Any] ?? [:]
            if path.hasSuffix("/rename") {
                writes += 1; let id = body["requestId"] as! String, name = body["name"] as! String
                jobs[id] = ["id": id, "threadId": "fixture", "kind": "rename", "name": name, "state": "uncertain", "result": ["threadId": "fixture", "name": name]]
                return ["id": "wrong-receipt", "threadId": "other", "kind": "rename", "name": name, "state": "failed"]
            }
            if path == "/api/jobs" { return ["jobs": []] }
            if path.hasPrefix("/api/jobs/") {
                queries += 1; let id = String(path.split(separator: "/").last!)
                if queries == 1 { return [:] }
                if queries == 3 || queries == 4 { return ["id": id, "threadId": "fixture", "kind": "rename", "name": "错误名称", "state": queries == 3 ? "failed" : "completed", "result": ["threadId": "fixture", "name": "新的中文名称 🧭"]] }
                if queries >= 5 { jobs[id]?["state"] = "completed" }; return jobs[id] ?? [:]
            }
            if path.contains("/history") { return ["thread": ["id": "fixture", "title": "新的中文名称 🧭"], "status": ["state": "idle"], "runtime": ["type": "idle"], "controls": ["supportedOperations": ["rename"]], "access": ["nativeReady": true, "canInteract": true], "timeline": []] }
            return [:]
        }
        func counts() -> (Int, Int) { lock.lock(); defer { lock.unlock() }; return (writes, queries) }
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
@MainActor @Observable private final class RenameFixture {
    let model = AppModel(); var show = false; var started = false; var presentation = 0; var scope = ""
    let thread = try! Record(.object(["id": .string("fixture"), "title": .string("旧名称")]))
    func wait() async { try? await Task.sleep(for: .milliseconds(650)) }
    func capture(_ filename: String = "rename") {
        guard let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent(filename + ".png"))
    }
    private func alert(in controller: UIViewController?) -> UIAlertController? {
        guard let controller else { return nil }
        if let alert = controller as? UIAlertController { return alert }
        if let alert = alert(in: controller.presentedViewController) { return alert }
        return controller.children.lazy.compactMap { self.alert(in: $0) }.first
    }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [RenameTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://rename-fixture.invalid/"), configuration: config))
        model.addressText = "https://rename-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "edit", "send"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true; model.selectedThread = thread
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.history = .object(["thread": thread.value, "status": .object(["state": .string("idle")]), "runtime": .object(["type": .string("idle")]), "controls": .object(["supportedOperations": .array([.string("rename")])])])
        model.draft = "保留本地草稿"; scope = model.scope; show = true; await wait()
        let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first
        let initialAlert = alert(in: window?.rootViewController)
        let nativeAlert = initialAlert?.title == "重命名任务" && initialAlert?.textFields?.first?.text == "旧名称" && Set(initialAlert?.actions.compactMap(\.title) ?? []) == Set(["取消", "保存"])
        capture("rename-alert")
        NotificationCenter.default.post(name: .init("fixture.rename.name"), object: "新的中文名称 🧭")
        model.historySynchronized = false
        NotificationCenter.default.post(name: .init("fixture.rename.save"), object: nil); await wait()
        let unsynced = RenameTransport.store.counts().0 == 0 && !model.pending.hasPending(scope: scope, target: thread.id)
        model.historySynchronized = true
        NotificationCenter.default.post(name: .init("fixture.rename.save"), object: nil); await wait()
        let malformedFailure = RenameTransport.store.counts().0 == 1 && model.pending.hasPending(scope: scope, target: thread.id)
        show = false; await wait(); presentation += 1; show = true; await wait(); capture()
        NotificationCenter.default.post(name: .init("fixture.rename.name"), object: "不应重新提交的名称")
        NotificationCenter.default.post(name: .init("fixture.rename.save"), object: nil); await wait()
        let queryOnly = RenameTransport.store.counts().0 == 1 && RenameTransport.store.counts().1 == 1
        NotificationCenter.default.post(name: .init("fixture.rename.restore"), object: nil); await wait(); capture()
        NotificationCenter.default.post(name: .init("fixture.rename.query"), object: nil); await wait()
        let wrongQueryPreserved = model.pending.hasPending(scope: scope, target: thread.id)
        NotificationCenter.default.post(name: .init("fixture.rename.query"), object: nil); await wait()
        let wrongNameSuccessPreserved = model.pending.hasPending(scope: scope, target: thread.id)
        NotificationCenter.default.post(name: .init("fixture.rename.query"), object: nil); await wait()
        let confirmed = model.selectedThread?.title == "新的中文名称 🧭" && !model.pending.hasPending(scope: scope, target: thread.id) && RenameTransport.store.counts().0 == 1
        let draftPreserved = model.draft == "保留本地草稿"
        show = false; await wait(); presentation += 1; show = true; await wait(); model.selectedDevice = "other"
        NotificationCenter.default.post(name: .init("fixture.rename.save"), object: nil); await wait()
        let staleScope = RenameTransport.store.counts().0 == 1
        let checks = ["nativePrefilledAlert": nativeAlert, "unsynced": unsynced, "malformedFailure": malformedFailure, "reopenedQueryOnly": queryOnly, "wrongQueryPreserved": wrongQueryPreserved, "wrongNameSuccessPreserved": wrongNameSuccessPreserved, "confirmed": confirmed, "draftPreserved": draftPreserved, "staleScope": staleScope]
        try? JSONSerialization.data(withJSONObject: ["passed": checks.values.allSatisfy { $0 }, "checks": checks]).write(to: URL.documentsDirectory.appendingPathComponent("rename-result.json"))
    }
}
