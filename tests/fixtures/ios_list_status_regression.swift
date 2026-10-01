import SwiftUI
import CarryOnCore

@main struct StatusRegressionApp: App {
    @State private var fixture = StatusFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                VStack {
                    RecordListView(path: "/api/projects", key: "projects", isProjectList: true, state: fixture.projects) { _ in }
                    RecordListView(path: "/api/workspace/threads", key: "threads", state: fixture.threads) { _ in }
                }
            }.environment(fixture.model).task { await fixture.run() }
        }
    }
}

private final class StatusTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        private let lock = NSLock()
        private var counts: [String: Int] = [:]
        private var probes: [String: Int] = [:]
        private var polls: [String: Int] = [:]
        func response(_ path: String) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let projects = path.contains("/api/projects")
            let key = projects ? "projects" : "threads"
            counts[key, default: 0] += 1
            if path.contains("refreshStatuses=true") { probes[key, default: 0] += 1 }
            if path.contains("sync=full") { return ["sync": ["id": key, "state": "running"]] }
            if path.contains("syncId=") {
                polls[key, default: 0] += 1
                if polls[key]! == 1 { return ["sync": ["id": key, "state": "running"]] }
            }
            let running = counts[key]! > 1
            let record: [String: Any] = projects
                ? ["id": "project", "name": "状态同步验证", "total": 200, "running": running ? 3 : 0]
                : ["id": "thread", "title": "会话执行状态", "projectName": "状态同步验证", "status": ["state": running ? "running" : "idle", "label": running ? "执行中" : "空闲"]]
            var response: [String: Any] = [key: [record], "total": 1, "nextOffset": 1]
            if path.contains("syncId=") { response["sync"] = ["id": key, "state": "completed"] }
            return response
        }
        func syncPolls(_ key: String) -> Int { lock.lock(); defer { lock.unlock() }; return polls[key, default: 0] }
        func requests(_ key: String) -> Int { lock.lock(); defer { lock.unlock() }; return counts[key, default: 0] }
        func refreshes(_ key: String) -> Int { lock.lock(); defer { lock.unlock() }; return probes[key, default: 0] }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }; bytes.append(buffer, count: n)
            }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let data = try! JSONSerialization.data(withJSONObject: Self.store.response(envelope["path"] as? String ?? ""))
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.5) { [self] in
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}

@MainActor @Observable final class StatusFixture {
    let model = AppModel()
    let projects = RecordListState()
    let threads = RecordListState()
    private var ran = false
    init() {
        UserDefaults.standard.set(false, forKey: "carryon.showInactiveConversations")
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [StatusTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://list-status.invalid/"), configuration: config))
        model.addressText = "https://list-status.invalid/"
        model.selectedDevice = "fixture"; model.connected = true
        model.devices = [try! Record(.object(["id": .string("fixture"), "permissions": .array([.string("view")])]))]
    }
    func packet(_ state: String, _ label: String, revision: Int) -> JSONValue {
        .object(["status": .object(["enabled": .bool(true)]), "workspaceRevision": .number(Double(revision)),
                 "threadStatuses": .object(["thread": .object(["state": .string(state), "label": .string(label)])])])
    }
    func run() async {
        guard !ran else { return }; ran = true
        try? await Task.sleep(for: .milliseconds(200))
        // Revision arrives while both first-page HTTP reads are in flight.
        await model.fixturePacket(packet("running", "执行中", revision: 1))
        try? await Task.sleep(for: .seconds(2))
        var checks: [String: Bool] = [:]
        checks["refreshDuringLoadIsReplayed"] = StatusTransport.store.requests("projects") == 2 && StatusTransport.store.requests("threads") == 2
        checks["projectCountsUseServerAggregate"] = projects.records.first?.value["running"].int == 3 && projects.records.first?.value["total"].int == 200
        checks["visibleThreadSubscribed"] = model.fixtureSelection()["threadIds"].array.contains(.string("thread"))
        guard let record = threads.records.first else {
            let result: [String: Any] = ["passed": false, "error": threads.failure ?? "No thread row", "checks": checks]
            try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("statuses-result.json"))
            return
        }
        await model.fixturePacket(packet("waiting", "待处理", revision: 1))
        checks["waitingUpdatesWithoutHTTP"] = model.listStatus(record)["state"].text == "waiting" && StatusTransport.store.requests("threads") == 2
        await model.fixturePacket(packet("idle", "空闲", revision: 1))
        checks["completionClearsRunning"] = model.listStatus(record)["state"].text == "idle"
        await model.fixturePacket(packet("loading", "检测中", revision: 1))
        checks["loadingIsDistinctFromIdle"] = model.listStatus(record)["state"].text == "loading"
        await model.fixturePacket(packet("running", "执行中", revision: 1))
        checks["nativeProbeRecoversRunning"] = model.listStatus(record)["state"].text == "running"
        NotificationCenter.default.post(name: Notification.Name("fixture.listRefresh"), object: nil)
        try? await Task.sleep(for: .seconds(1.2))
        checks["refreshWaitsForSyncCompletion"] = projects.loadKind == .refresh && threads.loadKind == .refresh
        try? await Task.sleep(for: .seconds(2))
        checks["refreshPollsUntilComplete"] = StatusTransport.store.syncPolls("threads") == 2 && StatusTransport.store.syncPolls("projects") == 2 && projects.loadKind == nil && threads.loadKind == nil
        checks["manualRefreshReprobesNativeStatus"] = StatusTransport.store.refreshes("threads") == 1 && StatusTransport.store.refreshes("projects") == 1
        model.connected = false
        checks["disconnectShowsUnconfirmed"] = model.listStatus(record)["state"].text == "unknown"
        model.connected = true
        // Capture the running row and project count in the real SwiftUI list.
        await model.fixturePacket(packet("running", "执行中", revision: 1))
        try? await Task.sleep(for: .milliseconds(200))
        if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("statuses.png"))
        }
        let owner = UUID()
        model.watchList(owner, threads: ["thread", "second"])
        model.watchList(threads.watchID, threads: [])
        checks["sharedWatchSurvivesListExit"] = Set(model.fixtureSelection()["threadIds"].array.map(\.text)) == ["thread", "second"]
        model.watchList(owner, threads: [])
        checks["exitReleasesWatch"] = model.fixtureSelection()["threadIds"].array.isEmpty && model.listThreadStatuses.isEmpty
        model.watchList(owner, threads: Set((1...150).map { "t\($0)" }))
        checks["subscriptionRespectsServerLimit"] = model.fixtureSelection()["threadIds"].array.count == 100
        model.fixtureResetScope()
        checks["workspaceResetClearsStatusesAndWatches"] = model.fixtureSelection()["threadIds"].array.isEmpty && model.listThreadStatuses.isEmpty
        let result: [String: Any] = ["passed": checks.values.allSatisfy { $0 }, "checks": checks]
        try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("statuses-result.json"))
    }
}
