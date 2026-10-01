import SwiftUI
import CarryOnCore

@main struct ActivityRegressionApp: App {
    @State private var fixture = ActivityFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                VStack {
                    ActivityRow(record: fixture.previewRow, scope: fixture.model.scope)
                    ActivityRow(record: fixture.emptyRow, scope: fixture.model.scope)
                }
            }.environment(fixture.model)
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.activity.state"))) {
                    fixture.viewState = $0.object as? [String: Bool] ?? [:]
                }
                .task { await fixture.run() }
        }
    }
}

private final class ActivityTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        private let lock = NSLock()
        private var count = 0
        private var failure = false
        private var delays: [Double] = []
        func configure(failure: Bool = false, delays: [Double] = []) {
            lock.lock(); defer { lock.unlock() }; self.failure = failure; self.delays = delays
        }
        func response(_ path: String) -> (Int, [String: Any], Double) {
            lock.lock(); defer { lock.unlock() }
            guard path.contains("/history") else { return (200, [:], 0) }
            count += 1
            let delay = delays.isEmpty ? 0.5 : delays.removeFirst()
            if failure { return (500, ["error": "fixture refresh failed"], delay) }
            let id = String(path.split(separator: "/")[2])
            return (200, ["thread": ["id": id], "source": "desktop-snapshot",
                "historyRevision": "history-\(count)", "status": ["state": "idle"],
                "access": ["canInteract": true, "nativeReady": true],
                "timeline": [["id": "turn", "type": "turn", "turnId": "turn", "status": "completed"],
                             ["id": "result", "type": "agentMessage", "turnId": "turn", "phase": "final", "text": "完整结果 \(count)"]]], delay)
        }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }; bytes.append(buffer, count: count)
            }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let (status, body, delay) = Self.store.response(envelope["path"] as? String ?? "")
        let data = try! JSONSerialization.data(withJSONObject: body)
        DispatchQueue.global().asyncAfter(deadline: .now() + delay) { [self] in
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}

@MainActor @Observable final class ActivityFixture {
    let model = AppModel()
    let previewRow = try! Record(.object(["id": .string("preview"), "title": .string("已有结果的动态"),
        "activityPreview": .object(["kind": .string("completed"), "turnId": .string("turn"), "text": .string("已有返回直接展示，后台刷新完整详情。")])]))
    let emptyRow = try! Record(.object(["id": .string("empty"), "title": .string("没有内容的动态")]))
    var viewState: [String: Bool] = [:]
    private var ran = false
    init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ActivityTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://activity.invalid/"), configuration: configuration))
        model.addressText = "https://activity.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "permissions": .array(["view", "approve", "send"].map { .string($0) })]))]
        model.authenticated = true; model.connected = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
    }
    private func pause(_ seconds: Double) async { try? await Task.sleep(for: .seconds(seconds)) }
    private func notify(_ action: String, _ id: String = "preview") {
        NotificationCenter.default.post(name: Notification.Name("fixture.activity." + action), object: id)
    }
    private func inspect(_ id: String = "preview") -> [String: Bool] {
        viewState = [:]; notify("inspect", id); return viewState
    }
    func run() async {
        guard !ran else { return }; ran = true
        var checks: [String: Bool] = [:]
        await pause(0.2)
        ActivityTransport.store.configure(delays: [1.5])
        notify("open"); await pause(0.6)
        checks["previewHasNoLoading"] = inspect()["loading"] == false && viewState["snapshot"] == false
        if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("activity.png"))
        }
        await pause(1.2)
        checks["freshResponseDisplaysFullResult"] = inspect()["snapshot"] == true && viewState["canPerform"] == true
        let target = ConversationActionTarget(scope: model.scope, threadID: "preview", isActivity: true)
        checks["freshResultStoredInExistingCache"] = model.displayCache.value(model.historyCacheKey("preview"))["thread"]["id"].text == "preview"
        notify("close"); await pause(0.7)
        checks["closingReleasesActiveSnapshot"] = model.activitySnapshots.isEmpty
        notify("open"); await pause(0.1)
        checks["reopenDisplaysCacheWithoutLoading"] = inspect()["snapshot"] == true && viewState["loading"] == false
        checks["cacheCannotAuthorizeOperations"] = viewState["canPerform"] == false
        await pause(0.7)
        checks["freshResponseRestoresNativeReadiness"] = inspect()["canPerform"] == true
        ActivityTransport.store.configure(failure: true)
        model.workspaceRevision += 1; await pause(0.7)
        checks["refreshFailureKeepsResultAndShowsError"] = inspect()["snapshot"] == true && viewState["failure"] == true && viewState["loading"] == false
        notify("close"); await pause(0.7)
        ActivityTransport.store.configure()
        notify("open", "empty"); await pause(0.1)
        checks["emptyDetailShowsInitialLoading"] = inspect("empty")["loading"] == true
        await pause(0.7)
        checks["emptyDetailStopsLoadingAfterResponse"] = inspect("empty")["loading"] == false && viewState["snapshot"] == true
        notify("close", "empty"); await pause(0.7)

        model.beginActivity(target, preview: .object(["turnId": .string("new-turn")]))
        checks["newTurnDoesNotReuseEarlierTurnResult"] = model.snapshot(for: target) == .null
        model.endActivity(target)
        model.beginActivity(target, preview: .null)
        ActivityTransport.store.configure(delays: [0.7, 0.1])
        let older = Task { try await model.loadActivity(target) }
        await pause(0.05)
        model.endActivity(target); model.beginActivity(target, preview: .null)
        let newer = Task { try await model.loadActivity(target) }
        do { try await newer.value } catch { checks["newerRequestSucceeded"] = false }
        let revision = model.snapshot(for: target)["historyRevision"]
        let oldResult = await older.result
        if case .failure(let error) = oldResult { checks["lateResponseIsRejected"] = error is CancellationError }
        else { checks["lateResponseIsRejected"] = false }
        checks["lateResponseCannotOverwriteReopenedDetail"] = model.snapshot(for: target)["historyRevision"] == revision
            && model.displayCache.value(model.historyCacheKey("preview"))["historyRevision"] == revision
        model.endActivity(target)
        let cached = model.displayCache.value(model.historyCacheKey("preview"))
        let unfinished = cached.setting("timeline", .array([
            .object(["id": .string("turn"), "type": .string("turn"), "turnId": .string("turn"), "status": .string("inProgress")])]))
        model.displayCache.store(unfinished, key: model.historyCacheKey("preview"), bytes: (try? unfinished.encoded().count) ?? -1)
        model.beginActivity(target, preview: previewRow.value["activityPreview"])
        checks["unfinishedCacheCannotHideCompletedPreview"] = model.snapshot(for: target) == .null
        model.endActivity(target)
        model.displayCache.store(cached, key: model.historyCacheKey("preview"), bytes: (try? cached.encoded().count) ?? -1)
        let other = ConversationActionTarget(scope: "another-workspace", threadID: "preview", isActivity: true)
        model.beginActivity(other, preview: .null)
        checks["cacheIsIsolatedByWorkspace"] = model.snapshot(for: other) == .null && model.activitySnapshots.isEmpty
        let result: [String: Any] = ["passed": checks.values.allSatisfy { $0 }, "checks": checks]
        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("activity-result.json"))
    }
}
