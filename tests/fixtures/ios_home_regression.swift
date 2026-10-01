import SwiftUI
import CarryOnCore

@main struct HomeRegressionApp: App {
    @State private var fixture = HomeFixture()
    var body: some Scene { WindowGroup { VStack { Text("首页刷新隔离验收"); Text(fixture.projects.failure ?? "读取中"); Text(fixture.threads.records.first?.title ?? "") }.sheet(isPresented: $fixture.showPicker) { CreationModelPicker(selection: $fixture.selection, scope: fixture.model.scope) }.environment(fixture.model).onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.model.state"))) { fixture.pickerState = $0.object as? [String: Any] ?? [:] }.task { await fixture.run() } } }
}
private final class HomeTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock()
        var paths: [String] = [], active = 0, maximum = 0, fail = false, removeModel = false
        func begin(_ path: String) { lock.lock(); defer { lock.unlock() }; paths.append(path); active += 1; maximum = max(maximum, active) }
        func response(_ path: String) -> (Int, [String: Any]) {
            lock.lock(); defer { lock.unlock() }; active -= 1
            if path == "/api/models" { return (200, ["models": removeModel ? [] : [["id": "fixture-model", "name": "Fixture", "efforts": ["medium", "high"], "defaultEffort": "medium"]]]) }
            if fail { return (503, ["error": "fixture refresh failed"]) }
            let field = path.contains("/projects") ? "projects" : "threads"
            if path.contains("sync=full") { return (200, ["sync": ["id": field, "state": "running"]]) }
            var result: [String: Any] = [field: [["id": field, "title": "最终状态", "name": "最终状态"]], "total": 1, "nextOffset": 1]
            if path.contains("syncId=") { result["sync"] = ["id": field, "state": "completed"] }
            return (200, result)
        }
        func snapshot() -> ([String], Int) { lock.lock(); defer { lock.unlock() }; return (paths, maximum) }
        func removeChoice() { lock.lock(); removeModel = true; lock.unlock() }
        func failReads() { lock.lock(); fail = true; lock.unlock() }
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
        let path = envelope["path"] as? String ?? ""
        Self.store.begin(path)
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.2) {
            let (status, body) = Self.store.response(path)
            self.client?.urlProtocol(self, didReceive: HTTPURLResponse(url: self.request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: body)); self.client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}
@MainActor @Observable final class HomeFixture {
    let model = AppModel(), projects = RecordListState(), threads = RecordListState(), loader = WorkspaceHomeLoader()
    var showPicker = false
    var selection: JSONValue = .null
    var pickerState: [String: Any] = [:]
    private var ran = false
    init() {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [HomeTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://home-regression.invalid/"), configuration: config))
        model.addressText = "https://home-regression.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "permissions": .array([.string("view")])]))]
        model.connected = true
    }
    func load(_ full: Bool = false) async { await loader.load(model: model, projects: projects, threads: threads, includeInactive: false, refresh: true, fullSync: full) }
    func openPicker() async {
        pickerState = [:]; let previous = HomeTransport.store.snapshot().0.count
        showPicker = true
        for _ in 0..<40 {
            try? await Task.sleep(for: .milliseconds(100))
            NotificationCenter.default.post(name: Notification.Name("fixture.model.inspect"), object: nil)
            if HomeTransport.store.snapshot().0.count > previous && pickerState["loading"] as? Bool == false { return }
        }
    }
    func run() async {
        guard !ran else { return }; ran = true
        let initial = Task { await load() }
        try? await Task.sleep(for: .milliseconds(50))
        for revision in 1...20 { model.workspaceRevision = revision; await load(revision == 4) }
        await initial.value
        let (paths, maximum) = HomeTransport.store.snapshot()
        var checks: [String: Bool] = [:]
        checks["revisionBurstCoalesced"] = paths.count == 6 && maximum == 1
        checks["manualFullSyncPreserved"] = paths.filter { $0.contains("sync=full") }.count == 2 && paths.filter { $0.contains("syncId=") }.count == 2
        checks["finalRowsPublished"] = projects.records.first?.title == "最终状态" && threads.records.first?.title == "最终状态"
        checks["loadingSettled"] = projects.loadKind == nil && threads.loadKind == nil
        HomeTransport.store.failReads(); await load()
        checks["failedRefreshRetainsRowsAndFailure"] = projects.records.count == 1 && threads.records.count == 1 && projects.failure != nil && threads.failure != nil
        await openPicker()
        NotificationCenter.default.post(name: Notification.Name("fixture.model.choose"), object: nil)
        try? await Task.sleep(for: .milliseconds(100))
        NotificationCenter.default.post(name: Notification.Name("fixture.model.save"), object: nil)
        try? await Task.sleep(for: .milliseconds(400))
        checks["chosenHighSaved"] = selection["model"].text == "fixture-model" && selection["effort"].text == "high"
        await openPicker()
        NotificationCenter.default.post(name: Notification.Name("fixture.model.inspect"), object: nil)
        checks["reopenedModelRetainsHigh"] = pickerState["selected"] as? String == "fixture-model" && pickerState["effort"] as? String == "high" && pickerState["loading"] as? Bool == false
        showPicker = false; try? await Task.sleep(for: .milliseconds(400))
        HomeTransport.store.removeChoice()
        await openPicker()
        NotificationCenter.default.post(name: Notification.Name("fixture.model.inspect"), object: nil)
        checks["removedModelShowsDefaultAndReason"] = pickerState["selected"] as? String == "" && !(pickerState["failure"] as? String ?? "").isEmpty && pickerState["loading"] as? Bool == false
        if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("home.png"))
        }
        let result: [String: Any] = ["passed": checks.values.allSatisfy { $0 }, "checks": checks, "requests": paths, "maximumConcurrent": maximum, "pickerState": pickerState, "allRequests": HomeTransport.store.snapshot().0]
        try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("home-result.json"))
    }
}
