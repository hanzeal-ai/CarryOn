import SwiftUI
import CarryOnCore
import UIKit

final class PluginTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        private let lock = NSLock()
        private var writes = 0
        private var queries = 0
        private var lastSearch: [String: Any]?
        func searchContext() -> [String: Any]? { lock.lock(); defer { lock.unlock() }; return lastSearch }
        private var discoveryBody: [String: Any]?
        func searchBody() -> [String: Any]? { lock.lock(); defer { lock.unlock() }; return discoveryBody }
        private var jobs: [String: [String: Any]] = [:]
        func counts() -> (Int, Int) { lock.lock(); defer { lock.unlock() }; return (writes, queries) }
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? "", body = envelope["body"] as? [String: Any] ?? [:]
            let plugin: [String: Any] = ["id": "fixture@market", "name": "fixture", "installed": queries >= 2, "enabled": queries >= 2, "marketplaceName": "测试市场", "marketplacePath": "/market/marketplace.json", "installPolicy": "AVAILABLE", "availability": "AVAILABLE", "authPolicy": "ON_INSTALL", "source": ["type": "local", "path": "/market/fixture"]]
            if path == "/api/threads/fixture/plugins", envelope["method"] as? String == "POST", body["discovery"] != nil {
                writes += 1; discoveryBody = body; let id = body["requestId"] as! String
                var fields = body; fields.removeValue(forKey: "requestId")
                return ["id": id, "threadId": "fixture", "kind": "plugin-" + (body["action"] as! String), "body": fields, "state": "completed", "result": ["threadId": "fixture", "pluginId": body["pluginId"]!, "installed": true, "appsNeedingAuth": []]]
            }
            let query = Dictionary((URLComponents(string: "https://fixture.invalid" + path)?.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { first, _ in first })
            if let term = query["search"] {
                let context: [String: Any] = ["searchTerm": term, "scope": query["scope"] ?? "global", "cursor": query["cursor"].map { $0 as Any } ?? NSNull()]
                lastSearch = context
                let number = query["cursor"] == nil ? 1 : 2
                let remote: [String: Any] = ["id": "remote-\(number)@market", "name": "remote-\(number)", "installed": false, "enabled": false, "marketplaceName": "远程市场", "marketplacePath": NSNull(), "installPolicy": "AVAILABLE", "availability": "AVAILABLE", "source": ["type": "git", "url": "https://example.invalid/plugins.git"], "discovery": context]
                if query["pluginId"] != nil { return ["threadId": "fixture", "plugin": ["summary": remote, "marketplaceName": "远程市场", "marketplacePath": NSNull(), "description": "原生分页搜索详情", "discovery": context]] }
                return ["threadId": "fixture", "plugins": [remote], "errors": [], "nextCursor": query["cursor"] == nil ? "opaque/+=" as Any : NSNull()]
            }
            if path == "/api/threads/fixture/plugins", envelope["method"] as? String == "POST" {
                writes += 1; let id = body["requestId"] as! String
                jobs[id] = ["id": id, "threadId": "fixture", "kind": "plugin-" + (body["action"] as! String), "body": ["action": body["action"]!, "pluginId": body["pluginId"]!], "state": "completed", "result": ["threadId": "fixture", "pluginId": body["pluginId"]!, "installed": body["action"] as? String == "install", "appsNeedingAuth": NSNull()]]
                return ["id": "wrong", "state": "failed"]
            }
            if path.hasPrefix("/api/threads/fixture/plugins?pluginId=") { return ["threadId": "fixture", "plugin": ["summary": plugin, "marketplaceName": "测试市场", "marketplacePath": "/market/marketplace.json", "description": "帮助检查界面与真实协议的一致性。", "skills": [["name": "review"]], "mcpServers": ["fixture-server"], "apps": [["name": "Fixture App"]], "hooks": [["event": "TurnStart"]]]] }
            if path == "/api/threads/fixture/plugins" { return ["threadId": "fixture", "plugins": [plugin], "errors": []] }
            if path.hasPrefix("/api/jobs/") { queries += 1; let id = String(path.split(separator: "/").last!); var job = jobs[id] ?? [:]; if queries == 2 { var result = job["result"] as! [String: Any]; result["appsNeedingAuth"] = ["malformed": true]; job["result"] = result }; if queries == 3 { job["state"] = "failed"; job["error"] = "fixture plugin operation rejected" }; if queries == 1 { job["body"] = ["action": "install", "pluginId": "wrong"]; job["state"] = "failed" }; return job }
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

@MainActor struct PluginRegression: View {
    @State private var model = AppModel()
    @State private var show = false
    @State private var started = false
    @State private var scope = ""
    @State private var presentation = 0
    @State private var snapshot: [String: Any] = [:]
    private let thread = try! Record(.object(["id": .string("fixture"), "title": .string("后台任务")]))
    var body: some View {
        Color.clear.environment(model).sheet(isPresented: $show) { PluginManagementView(thread: thread, scope: model.scope).id(presentation).environment(model) }
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.snapshot"))) { snapshot = $0.object as? [String: Any] ?? [:] }
            .task { await run() }
    }
    func wait() async { try? await Task.sleep(for: .milliseconds(650)) }
    func inspect() { NotificationCenter.default.post(name: .init("fixture.plugins.inspect"), object: nil) }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [PluginTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://plugins-fixture.invalid/"), configuration: config))
        model.addressText = "https://plugins-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "edit"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true; model.selectedThread = thread
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true), "supportsPluginManagement": .bool(true)])
        model.history = .object(["thread": thread.value, "status": .object(["state": .string("idle")]), "access": .object(["canInteract": .bool(true)]), "controls": .object(["supportsSkills": .bool(true)])])
        scope = model.scope
        for id in (try? model.pending.requestIDs(scope: scope, target: "plugin-management")) ?? [] { try? model.pending.resolve(scope: scope, target: "plugin-management", requestID: id) }
        model.draft = "保留草稿"; show = true; await wait(); inspect()
        let loaded = snapshot["loaded"] as? Bool == true && snapshot["rows"] as? Int == 1
        NotificationCenter.default.post(name: .init("fixture.plugins.search"), object: "不存在"); await wait(); inspect()
        let noMatch = snapshot["filteredRows"] as? Int == 0 && PluginTransport.store.counts().0 == 0
        NotificationCenter.default.post(name: .init("fixture.plugins.search"), object: "测试市场"); await wait(); inspect()
        let match = snapshot["filteredRows"] as? Int == 1 && PluginTransport.store.counts().0 == 0
        NotificationCenter.default.post(name: .init("fixture.plugins.detail"), object: nil); await wait(); inspect()
        let detailLoaded = snapshot["detail"] as? Bool == true
        if let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first { let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }; try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("plugins.png")) }
        model.history = model.history.setting("access", .object(["canInteract": .bool(false)]))
        NotificationCenter.default.post(name: .init("fixture.plugins.stop"), object: nil); await wait()
        let readOnlyBlocks = PluginTransport.store.counts().0 == 0
        model.history = model.history.setting("access", .object(["canInteract": .bool(true)]))
        NotificationCenter.default.post(name: .init("fixture.plugins.stop"), object: nil); await wait()
        let unknownRetained = model.pending.hasPending(scope: scope, target: "plugin-management") && PluginTransport.store.counts().0 == 1
        show = false; await wait(); presentation += 1; show = true; await wait()
        let wrongRestoreRetained = model.pending.hasPending(scope: scope, target: "plugin-management") && PluginTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.plugins.stop"), object: nil); await wait()
        let noReplay = PluginTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.plugins.check"), object: nil); await wait()
        inspect(); let authUnknown = snapshot["failure"] as? String == "已安装，应用授权状态待核对"
        let confirmed = !model.pending.hasPending(scope: scope, target: "plugin-management") && PluginTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.plugins.detail"), object: nil); await wait()
        NotificationCenter.default.post(name: .init("fixture.plugins.stop"), object: nil); await wait()
        NotificationCenter.default.post(name: .init("fixture.plugins.check"), object: nil); await wait(); inspect()
        let failedVisible = snapshot["failure"] as? String == "fixture plugin operation rejected" && !model.pending.hasPending(scope: scope, target: "plugin-management")
        NotificationCenter.default.post(name: .init("fixture.plugins.mode"), object: "global"); await wait()
        NotificationCenter.default.post(name: .init("fixture.plugins.search"), object: "远程 fixture")
        NotificationCenter.default.post(name: .init("fixture.plugins.nativeSearch"), object: false); await wait(); inspect()
        let firstSearch = snapshot["rows"] as? Int == 1 && snapshot["nextCursor"] as? String == "opaque/+=" && PluginTransport.store.counts().0 == 2
        NotificationCenter.default.post(name: .init("fixture.plugins.search"), object: "");
        NotificationCenter.default.post(name: .init("fixture.plugins.nativeSearch"), object: true); await wait(); inspect()
        let paginated = snapshot["rows"] as? Int == 2 && snapshot["nextCursor"] as? String == "" && PluginTransport.store.counts().0 == 2
        if let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first { let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }; try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("plugins-search.png")) }
        NotificationCenter.default.post(name: .init("fixture.plugins.search"), object: "未提交的新查询")
        NotificationCenter.default.post(name: .init("fixture.plugins.detail"), object: "remote-2@market"); await wait()
        NotificationCenter.default.post(name: .init("fixture.plugins.stop"), object: nil); await wait()
        let sent = PluginTransport.store.searchBody(), discovery = sent?["discovery"] as? [String: Any]
        let refreshed = PluginTransport.store.searchContext()
        let refreshOriginal = refreshed?["searchTerm"] as? String == "远程 fixture" && refreshed?["cursor"] is NSNull
        let searchInstalled = sent?["pluginId"] as? String == "remote-2@market" && discovery?["searchTerm"] as? String == "远程 fixture" && discovery?["scope"] as? String == "global" && discovery?["cursor"] as? String == "opaque/+=" && PluginTransport.store.counts().0 == 3 && !model.pending.hasPending(scope: scope, target: "plugin-management")
        let draft = model.draft == "保留草稿"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array([])]))]; await wait(); inspect()
        let revoked = snapshot["rows"] as? Int == 0 && !show
        let checks = ["refreshKeepsSubmittedQuery": refreshOriginal, "nativeSearchFirstPage": firstSearch, "nativeSearchPagination": paginated, "nativeSearchInstallationIdentity": searchInstalled, "directorySearch": noMatch && match, "readOnlyBlocks": readOnlyBlocks, "detailLoaded": detailLoaded, "authUnknown": authUnknown, "failedWriteRemainsVisible": failedVisible, "loadedNativeInventory": loaded, "unknownRetained": unknownRetained, "wrongRestoreRetained": wrongRestoreRetained, "noReplay": noReplay, "canonicalConfirmed": confirmed, "draftPreserved": draft, "revokeClearsRows": revoked]
        try? JSONSerialization.data(withJSONObject: ["passed": checks.values.allSatisfy { $0 }, "checks": checks, "diagnostic": snapshot]).write(to: URL.documentsDirectory.appendingPathComponent("plugins-result.json"))
    }
}
@main struct CarryOnApp: App { var body: some Scene { WindowGroup { PluginRegression() } } }
