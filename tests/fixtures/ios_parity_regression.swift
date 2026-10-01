import SwiftUI
import CarryOnCore
import Foundation

@main struct ParityApp: App {
    @State private var fixture = ParityFixture()
    var body: some Scene {
        WindowGroup {
            Group {
                if fixture.phase == 0 { NewConversationView() }
                else if fixture.phase == 1 { ConversationChangesView(threadID: "fixture", scopedHistory: fixture.history) }
                else if fixture.phase == 2 { SkillsPickerView(target: .init(scope: fixture.model.scope, threadID: "fixture")) }
                else { ConversationGoalView(target: .init(scope: fixture.model.scope, threadID: "fixture")) }
            }.environment(fixture.model).task { await fixture.run() }
        }
    }
}
private final class MockTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock()
        var jobs: [String: [String: Any]] = [:]
        var captures: [[String: Any]] = []
        var creationPolls = 0
        var lostReplyIDs: Set<String> = []
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? ""
            let body = envelope["body"] as? [String: Any] ?? [:]
            captures.append(envelope)
            if path.contains("/api/jobs/") {
                let id = String(path.split(separator: "/").last ?? "")
                if lostReplyIDs.contains(id) { return ["fixtureLostReply": true] }
                if jobs[id]?["kind"] as? String == "create" {
                    creationPolls += 1
                    if creationPolls >= 2 { jobs[id]?["state"] = "completed"; jobs[id]?["createdThreadId"] = "new-native-thread" }
                }
                return jobs[id] ?? ["state": "failed", "error": "unknown fixture job"]
            }
            if path.hasSuffix("/operations") || path.hasSuffix("/compose") {
                let id = body["requestId"] as? String ?? ""
                if body["prompt"] as? String == "live accepted lost reply" { lostReplyIDs.insert(id) }
                let failed = (body["prompt"] as? String ?? "").contains("fail")
                jobs[id] = ["id": id, "threadId": path.contains("side-chats") ? "side" : "fixture", "kind": path.hasSuffix("/compose") ? "message" : "operation:\(body["action"] ?? "")", "clientMessageId": id, "turnId": "turn-" + id, "state": (body["prompt"] as? String) == "uncertain" ? "uncertain" : failed ? "failed" : path.hasSuffix("/compose") ? "accepted" : "completed", "error": failed ? "排队消息已变化" : ""]
                return ["id": id, "state": "preparing", "threadId": path.contains("side-chats") ? "side" : "fixture", "kind": "operation:\(body["action"] ?? "")"]
            }
            if path == "/api/threads" {
                let id = body["requestId"] as? String ?? ""
                jobs[id] = ["id": id, "threadId": "", "kind": "create", "state": "accepted"]
                return jobs[id]!
            }
            if path == "/api/activity" { return ["threads": [], "total": 0, "nextOffset": 0] }
            if path.hasPrefix("/api/projects") { return ["projects": [["id": "p", "title": "CarryOn", "cwd": "/workspace/CarryOn"]], "total": 1, "nextOffset": 1] }
            if path.hasSuffix("/skills") { return ["cwd": "/workspace/CarryOn", "skills": [
                ["name": "code-review", "path": "/skills/code-review/SKILL.md", "enabled": true, "description": "检查代码改动、边界条件与测试覆盖"],
                ["name": "frontend-design", "path": "/skills/frontend-design/SKILL.md", "enabled": true, "description": "设计和实现界面，验证实际渲染"],
                ["name": "disabled", "path": "/skills/disabled/SKILL.md", "enabled": false, "description": "已禁用"]], "errors": []] }
            if path == "/api/models" { return ["models": [["id": "gpt-5.5", "name": "5.5", "efforts": ["medium", "high"], "defaultEffort": "medium"]]] }
            return [:]
        }
        func all() -> [[String: Any]] { lock.lock(); defer { lock.unlock() }; return captures }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; bytes.append(buffer, count: n) }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let value = Self.store.respond(envelope)
        let response = HTTPURLResponse(url: request.url!, statusCode: value["fixtureLostReply"] as? Bool == true ? 503 : (envelope["body"] as? [String: Any])?["prompt"] as? String == "reject-http" ? 403 : 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: value))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}


@MainActor @Observable final class ParityFixture {
    let model = AppModel()
    var phase = 0
    var history: JSONValue = .null
    private var started = false
    private func capture(_ name: String) {
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent(name + ".png"))
    }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [MockTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://ios-parity.invalid/"), configuration: config))
        model.addressText = "https://ios-parity.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "title": .string("Office"), "online": .bool(true), "permissions": .array(["view", "send", "create", "edit"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        try? await Task.sleep(for: .seconds(2))
        _ = try? await model.cachedDeviceRequest("/api/models", maxAge: 0)
        NotificationCenter.default.post(name: Notification.Name("fixture.creation"), object: nil)
        try? await Task.sleep(for: .milliseconds(500)); capture("parity-new")
        let creationKey = model.scope + "\nnew"
        model.draftStore.texts[creationKey] = "请检查这个项目"
        NotificationCenter.default.post(name: Notification.Name("fixture.composer.focus"), object: nil)
        try? await Task.sleep(for: .seconds(1))
        try? Data().write(to: URL.documentsDirectory.appendingPathComponent("parity-new-single.capture"))
        try? await Task.sleep(for: .seconds(1))
        model.draftStore.texts[creationKey] = "检查 iOS 会话输入框。\n保留已有草稿和图片。\n确认键盘展开时控件没有遮挡。"
        try? await Task.sleep(for: .milliseconds(500))
        try? Data().write(to: URL.documentsDirectory.appendingPathComponent("parity-new-multiline.capture"))
        try? await Task.sleep(for: .seconds(1))
        let image = UIGraphicsImageRenderer(size: CGSize(width: 120, height: 80)).image { context in
            UIColor.systemBlue.setFill(); context.fill(CGRect(x: 0, y: 0, width: 120, height: 80))
            ("Fixture image" as NSString).draw(at: CGPoint(x: 10, y: 25), withAttributes: [.foregroundColor: UIColor.white])
        }
        model.draftStore.images[creationKey] = ["data:image/png;base64," + image.pngData()!.base64EncodedString()]
        try? await Task.sleep(for: .milliseconds(500))
        try? Data().write(to: URL.documentsDirectory.appendingPathComponent("parity-new-image.capture"))
        try? await Task.sleep(for: .seconds(1))
        let patch = "@@ -1,2 +1,3 @@\n let value = 1\n-old()\n+new()\n+verify()"
        let change: JSONValue = .object(["path": .string("src/example.swift"), "diff": .string(patch)])
        let entry: JSONValue = .object(["id": .string("change"), "type": .string("fileChange"), "status": .string("completed"), "data": .object(["changes": .array([change])])])
        history = .object(["thread": .object(["id": .string("fixture")]), "timeline": .array([entry])])
        let scope = model.scope, key = scope + "\nfixture"
        model.draftStore.texts[key] = "保留已有草稿"; model.draftStore.images[key] = ["fixture-image"]
        phase = 1; try? await Task.sleep(for: .seconds(1)); capture("parity-diff")
        NotificationCenter.default.post(name: Notification.Name("fixture.comment"), object: nil)
        try? await Task.sleep(for: .milliseconds(700)); capture("parity")
        model.selectedDevice = "other"
        NotificationCenter.default.post(name: Notification.Name("fixture.submitComment"), object: nil)
        let scoped = model.draftStore.texts[key] == "保留已有草稿" && model.draftStore.texts[model.scope + "\nfixture"] == nil
        model.selectedDevice = "fixture"
        NotificationCenter.default.post(name: Notification.Name("fixture.submitComment"), object: nil)
        try? await Task.sleep(for: .milliseconds(200))
        let draft = model.draftStore.texts[key] ?? ""
        let appended = draft.hasPrefix("保留已有草稿") && draft.contains("src/example.swift（R2）") && draft.contains("请检查这里的边界")
        let noSend = !MockTransport.store.all().contains { ($0["path"] as? String ?? "").contains("/compose") || ($0["path"] as? String ?? "").contains("/operations") }
        let imagesRetained = model.draftStore.images[key] == ["fixture-image"]
        model.selectedThread = try! Record(.object(["id": .string("fixture"), "title": .string("CarryOn")]))
        model.history = history.setting("controls", .object(["supportsSkills": .bool(true)]))
        model.draftSkills = [.init(name: "code-review", path: "/skills/code-review/SKILL.md")]
        phase = 2; try? await Task.sleep(for: .seconds(1)); capture("parity-skills")
        model.historySynchronized = true
        model.history = model.history.setting("source", .string("desktop-snapshot")).setting("status", .object(["state": .string("running")])).setting("access", .object(["nativeReady": .bool(true), "canInteract": .bool(true)])).setting("controls", .object(["supportsGoal": .bool(true), "goal": .object([
            "threadId": .string("fixture"), "objective": .string("完成原生审查与目标管理，并验证跨端行为"), "status": .string("active"),
            "tokenBudget": .number(50000), "tokensUsed": .number(12400), "timeUsedSeconds": .number(420)])]))
        phase = 3; try? await Task.sleep(for: .seconds(1)); capture("parity-goal")
        let result: [String: Any] = ["passed": scoped && appended && noSend && imagesRetained, "scopeIsolation": scoped, "commentAppended": appended, "noAutomaticSend": noSend, "imagesRetained": imagesRetained]
        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("parity-result.json"))
    }
}
