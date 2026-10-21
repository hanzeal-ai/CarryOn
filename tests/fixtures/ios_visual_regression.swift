import SwiftUI
import CarryOnCore

// Production home with a comparable three-project, connected, error-free fixture.
@main struct VisualRegressionApp: App {
    @State private var fixture = VisualFixture()
    var body: some Scene { WindowGroup { RootView().environment(fixture.model).task { await fixture.run() } } }
}
private final class VisualTransport: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if let stream = request.httpBodyStream, bytes.isEmpty {
            stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; bytes.append(buffer, count: count) }
        }
        let requestBody = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let path = requestBody["path"] as? String ?? ""
        let projects = ["openai", "superassistant", "codex"].map { ["id": $0, "name": $0, "title": $0, "cwd": "/workspace/" + $0, "total": 1] as [String: Any] }
        let threads: [[String: Any]] = [
            ["id": "recent", "title": "检查项目改动", "projectId": "codex", "projectName": "codex", "cwd": "/workspace/codex", "runtime": ["type": "idle"], "status": ["state": "idle", "label": "已完成"], "updatedAt": 1_790_899_200],
            ["id": "running", "title": "完善移动端交互", "projectId": "openai", "projectName": "openai", "runtime": ["type": "running"], "status": ["state": "running", "label": "执行中"]],
            ["id": "waiting", "title": "核对样式与截图", "projectId": "superassistant", "projectName": "superassistant", "runtime": ["type": "idle"], "status": ["state": "idle", "label": "已完成"]]
        ]
        let field = path.hasPrefix("/api/projects") ? "projects" : "threads"
        let query = URLComponents(string: "https://fixture.invalid" + path)?.queryItems?.first { $0.name == "search" }?.value ?? ""
        let rows = field == "projects" ? projects : threads.filter { query.isEmpty || ($0["title"] as? String ?? "").localizedCaseInsensitiveContains(query) }
        var response: [String: Any] = [field: rows, "total": rows.count, "nextOffset": rows.count]
        if path.hasPrefix("/api/models") {
            response = ["models": [["id": "fixture-model", "name": "Fixture", "efforts": ["low", "medium", "high"], "defaultEffort": "medium"]]]
        }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: response)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
@MainActor @Observable final class VisualFixture {
    let model = AppModel()
    private var started = false
    init() {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [VisualTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://visual-regression.invalid/"), configuration: config))
        model.addressText = "https://visual-regression.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "title": .string("MacBook"), "online": .bool(true), "permissions": .array(["view", "create", "send", "edit", "stop"].map(JSONValue.string))]))]
        model.restoringLogin = false; model.authenticated = true; model.connected = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        UserDefaults.standard.set(false, forKey: "carryon.showInactiveConversations")
    }
    func run() async {
        guard !started else { return }; started = true
        try? await Task.sleep(for: .seconds(2))
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("visual.png"))
        let result: [String: Any] = ["passed": model.error == nil && model.selectedThread == nil && model.connected, "fixture": "three projects, connected, production RootView"]
        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("visual-result.json"))
    }
}
