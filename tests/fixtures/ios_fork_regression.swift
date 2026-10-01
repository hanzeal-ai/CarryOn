import SwiftUI
import CarryOnCore

@main struct ForkRegressionApp: App {
    @State private var fixture = ForkFixture()
    var body: some Scene { WindowGroup {
        Text("分叉隔离验证").sheet(isPresented: $fixture.showFork) { ForkConversationView(thread: fixture.source, scope: fixture.originScope) { fixture.completions += 1 } }
            .environment(fixture.model)
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.fork.finished"))) { _ in fixture.finished = true }
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.fork.errorVisible"))) { note in fixture.visibleError = note.object as? String ?? "" }
            .task { await fixture.run() }
    } }
}
private final class ForkTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock(); var mode = "completed", writes: [[String: Any]] = []
        func set(_ value: String) { lock.lock(); mode = value; lock.unlock() }
        func capture(_ body: [String: Any]) -> String { lock.lock(); defer { lock.unlock() }; writes.append(body); return mode }
        func all() -> [[String: Any]] { lock.lock(); defer { lock.unlock() }; return writes }
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
        let path = envelope["path"] as? String ?? "", body = envelope["body"] as? [String: Any] ?? [:]
        let mode = path.hasSuffix("/fork") ? Self.store.capture(body) : "read"
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.25) {
            var value: [String: Any] = mode == "read" ? [:] : ["id": body["requestId"] ?? "", "state": mode == "missing" ? "completed" : mode, "threadId": "source"]
            if mode != "read" && mode != "missing" { value["createdThreadId"] = "forked" }
            self.client?.urlProtocol(self, didReceive: HTTPURLResponse(url: self.request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: value)); self.client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}
@MainActor @Observable final class ForkFixture {
    let model = AppModel(), source = try! Record(.object(["id": .string("source"), "title": .string("分叉验证")]))
    var originScope = ""
    var completions = 0
    var visibleError = ""
    var finished = false
    var showFork = true
    private var ran = false
    init() {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ForkTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://fork-regression.invalid/"), configuration: config))
        model.addressText = "https://fork-regression.invalid/"; model.selectedDevice = "fixture"; originScope = model.scope
        reset()
    }
    func reset(_ create: Bool = true) {
        model.selectedDevice = "fixture"; model.selectedThread = source
        model.devices = [try! Record(.object(["id": .string("fixture"), "permissions": .array((create ? ["view", "create"] : ["view"]).map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.history = .object(["thread": .object(["id": .string("source")]), "status": .object(["state": .string("idle")]), "controls": .object(["supportedOperations": .array([.string("fork")])]), "timeline": .array([.object(["id": .string("m"), "type": .string("userMessage"), "turnId": .string("turn-1"), "text": .string("第一轮")])])])
        model.error = nil; finished = false
    }
    func submit(_ turn: String) async {
        finished = false; showFork = true
        try? await Task.sleep(for: .milliseconds(500))
        NotificationCenter.default.post(name: Notification.Name("fixture.fork.submit"), object: turn)
    }
    func wait() async { for _ in 0..<40 { if finished { return }; try? await Task.sleep(for: .milliseconds(100)) } }
    func run() async {
        guard !ran else { return }; ran = true; try? await Task.sleep(for: .milliseconds(400))
        var checks: [String: Bool] = [:]
        reset(false); await submit(""); await wait(); checks["withoutCreateDenied"] = ForkTransport.store.all().isEmpty && completions == 0
        reset(); ForkTransport.store.set("completed"); await submit("turn-1"); await wait()
        let body = ForkTransport.store.all().last ?? [:]
        checks["selectedTurnBodyExact"] = Set(body.keys) == ["requestId", "lastTurnId"] && body["lastTurnId"] as? String == "turn-1"
        checks["confirmedIDNavigates"] = model.selectedThread?.id == "forked" && completions == 1
        reset(); await submit(""); try? await Task.sleep(for: .milliseconds(80)); model.selectedThread = try! Record(.object(["id": .string("other")]))
        await wait(); checks["sourceChangeDoesNotNavigate"] = ForkTransport.store.all().count == 2 && model.selectedThread?.id == "other" && completions == 1
        reset(); await submit(""); try? await Task.sleep(for: .milliseconds(80)); model.selectedDevice = "other"
        await wait(); checks["scopeChangeDoesNotNavigate"] = ForkTransport.store.all().count == 3 && model.selectedDevice == "other" && completions == 1
        reset(); ForkTransport.store.set("uncertain"); await submit(""); await wait(); let first = ForkTransport.store.all().last?["requestId"] as? String
        await submit(""); await wait(); let second = ForkTransport.store.all().last?["requestId"] as? String
        checks["uncertainPreservesRequestID"] = ForkTransport.store.all().count == 5 && first != nil && first == second && model.selectedThread?.id == "source" && completions == 1
        reset(); ForkTransport.store.set("accepted"); await submit("turn-1"); await wait(); checks["acceptedDoesNotNavigate"] = ForkTransport.store.all().count == 6 && model.selectedThread?.id == "source" && completions == 1
        reset(); ForkTransport.store.set("missing"); await submit("turn-1"); await wait(); checks["missingIDDoesNotNavigate"] = ForkTransport.store.all().count == 7 && model.selectedThread?.id == "source" && completions == 1
        let missingID = ForkTransport.store.all().last?["requestId"] as? String
        await submit("turn-1"); await wait()
        checks["missingIDPreservesRequestID"] = ForkTransport.store.all().count == 8 && missingID != nil && missingID == ForkTransport.store.all().last?["requestId"] as? String
        ForkTransport.store.set("accepted"); await submit("turn-1"); await wait()
        checks["acceptedPreservesRequestID"] = ForkTransport.store.all().count == 9 && missingID == ForkTransport.store.all().last?["requestId"] as? String && completions == 1
        ForkTransport.store.set("failed"); await submit("turn-1"); await wait()
        let failedID = ForkTransport.store.all().last?["requestId"] as? String
        await submit("turn-1"); await wait()
        checks["failedAllowsNewRequestID"] = ForkTransport.store.all().count == 11 && failedID != nil && failedID != ForkTransport.store.all().last?["requestId"] as? String && completions == 1
        await submit("removed-turn"); await wait()
        checks["unavailableTurnDoesNotWrite"] = ForkTransport.store.all().count == 11
        try? await Task.sleep(for: .milliseconds(400))
        checks["failureVisibleInForm"] = visibleError == "操作失败"
        if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("fork.png"))
        }
        let result: [String: Any] = ["passed": checks.values.allSatisfy { $0 }, "checks": checks, "writes": ForkTransport.store.all(), "error": model.error ?? "", "canInteract": model.canInteract, "canWrite": model.canWrite, "finished": finished, "showFork": showFork, "scope": model.scope, "origin": originScope]
        try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("fork-result.json"))
    }
}
