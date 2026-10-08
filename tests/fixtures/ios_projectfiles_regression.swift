import SwiftUI
import CarryOnCore

@main struct ProjectFilesRegressionApp: App {
    var body: some Scene { WindowGroup { ProjectFilesFixture() } }
}
@MainActor struct ProjectFilesFixture: View {
    @State private var model = AppModel()
    @State private var show = false
    @State private var started = false
    @State private var scope = ""
    @State private var snapshot: [String: Any] = [:]
    private let thread = try! Record(.object(["id": .string("fixture"), "title": .string("项目文件")]))
    var body: some View {
        Color.clear.environment(model).sheet(isPresented: $show) { ProjectFilesPicker(threadID: thread.id, scope: model.scope).environment(model) }
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.files.snapshot"))) { snapshot = $0.object as? [String: Any] ?? [:] }
            .task { await run() }
    }
    func wait() async { try? await Task.sleep(for: .milliseconds(600)) }
    func inspect() { NotificationCenter.default.post(name: .init("fixture.files.inspect"), object: nil) }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ProjectFileTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://files-fixture.invalid/"), configuration: config))
        model.addressText = "https://files-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "send", "files"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true; model.selectedThread = thread
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.history = .object(["thread": thread.value, "status": .object(["state": .string("idle")]), "access": .object(["canInteract": .bool(true), "nativeReady": .bool(true)]), "controls": .object(["supportsFileReferences": .bool(true)])])
        scope = model.scope; model.draft = "检查项目"; model.draftFiles = []; show = true; await wait()
        NotificationCenter.default.post(name: .init("fixture.files.search"), object: "README"); await wait(); inspect()
        var results: [String: Bool] = [:]
        results["nativeSearch"] = snapshot["count"] as? Int == 1 && ProjectFileTransport.store.queries == ["README"]
        NotificationCenter.default.post(name: .init("fixture.files.toggle"), object: nil); await wait(); inspect()
        results["selectionKeepsQuery"] = model.draftFiles == [.init(name: "README.md", path: "/project/docs/README.md", query: "README")] && model.draft == "检查项目"
        if let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("projectfiles.png"))
        }
        NotificationCenter.default.post(name: .init("fixture.files.toggle"), object: nil); await wait()
        results["deselect"] = model.draftFiles.isEmpty
        NotificationCenter.default.post(name: .init("fixture.files.toggle"), object: nil); await wait()
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "send"].map(JSONValue.string))]))]
        await wait(); let previous = ProjectFileTransport.store.queries.count
        NotificationCenter.default.post(name: .init("fixture.files.search"), object: "forbidden"); await wait()
        results["revocationClosesAndBlocks"] = !show && ProjectFileTransport.store.queries.count == previous
        results["revocationKeepsDraft"] = model.draftFiles.count == 1 && model.draft == "检查项目"
        results["passed"] = results.values.allSatisfy { $0 }
        try? JSONSerialization.data(withJSONObject: results.mapValues { $0 as Any }.merging(["snapshot": snapshot, "queries": ProjectFileTransport.store.queries, "canCompose": model.canCompose, "draftFiles": model.draftFiles.map { $0.path }, "shown": show] as [String: Any]) { _, new in new }).write(to: URL.documentsDirectory.appendingPathComponent("projectfiles-result.json"))
    }
}
final class ProjectFileStore: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String] = []
    var queries: [String] { lock.withLock { values } }
    func add(_ value: String) { lock.withLock { values.append(value) } }
}
final class ProjectFileTransport: URLProtocol, @unchecked Sendable {
    static let store = ProjectFileStore()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data: [String: Any] = [:]
        var body = request.httpBody ?? Data()
        if body.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; body.append(contentsOf: buffer.prefix(count)) }
        }
        if let env = try? JSONSerialization.jsonObject(with: body) as? [String: Any], let path = env["path"] as? String {
            if path.contains("/files/search"), let term = URLComponents(string: "https://fixture" + path)?.queryItems?.first(where: { $0.name == "query" })?.value {
                Self.store.add(term); data = ["threadId": "fixture", "files": [["name": "README.md", "path": "/project/docs/README.md", "relativePath": "docs/README.md", "query": term]]]
            }
        }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: (try? JSONSerialization.data(withJSONObject: data)) ?? Data()); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
