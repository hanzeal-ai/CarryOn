import SwiftUI
import CarryOnCore
import Foundation
@main struct CreationReferencesApp: App {
    @State private var fixture = CreationReferencesFixture()
    var body: some Scene { WindowGroup { NewConversationView().environment(fixture.model).task { await fixture.run() } } }
}
private final class MockTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock()
        var jobs: [String: [String: Any]] = [:]
        var captures: [[String: Any]] = []
        var modelDelay = 0.0
        var validModelCatalog = true
        func configureModels(delay: Double, valid: Bool = true) { lock.lock(); defer { lock.unlock() }; modelDelay = delay; validModelCatalog = valid }
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
                jobs[id] = ["id": id, "threadId": "", "kind": "create", "state": "failed", "error": "fixture rejection"]
                if body["prompt"] as? String == "unconfirmed create" { jobs[id] = ["id": id, "kind": "create", "state": "completed"] }
                if body["prompt"] as? String == "confirmed create" { jobs[id] = ["id": id, "kind": "create", "state": "completed", "createdThreadId": "confirmed-native"] }
                return jobs[id]!
            }
            if path == "/api/activity" { return ["threads": [], "total": 0, "nextOffset": 0] }
            if path.hasPrefix("/api/projects") { return ["projects": [["id": "p", "title": "CarryOn", "cwd": "/workspace/CarryOn"]], "total": 1, "nextOffset": 1] }
            if path.hasSuffix("/skills") { return ["cwd": "/workspace/CarryOn", "skills": [
                ["name": "code-review", "path": "/skills/code-review/SKILL.md", "enabled": true, "description": "检查代码改动、边界条件与测试覆盖"],
                ["name": "frontend-design", "path": "/skills/frontend-design/SKILL.md", "enabled": true, "description": "设计和实现界面，验证实际渲染"],
                ["name": "disabled", "path": "/skills/disabled/SKILL.md", "enabled": false, "description": "已禁用"]], "errors": []] }
            if path == "/api/models" { return ["fixtureDelay": modelDelay, "models": validModelCatalog ? [["id": "gpt-5.5", "name": "5.5", "efforts": ["medium", "high"], "defaultEffort": "medium"]] : "invalid" as Any] }
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
        let data = try! JSONSerialization.data(withJSONObject: value)
        if let delay = value["fixtureDelay"] as? Double, delay > 0 {
            DispatchQueue.global().asyncAfter(deadline: .now() + delay) { self.deliver(response, data: data) }
        } else { deliver(response, data: data) }
    }
    private func deliver(_ response: HTTPURLResponse, data: Data) {
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}



@MainActor @Observable final class CreationReferencesFixture {
    let model = AppModel()
    private var started = false
    init() {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [MockTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://creationrefs.invalid/"), configuration: config))
        model.addressText = "https://creationrefs.invalid/"; model.selectedDevice = "a"
        model.devices = ["a", "b"].map { try! Record(.object(["id": .string($0), "title": .string("Office " + $0), "online": .bool(true), "permissions": .array(["view", "create", "send", "edit"].map(JSONValue.string))])) }
        model.restoringLogin = false; model.authenticated = true; model.connected = true; model.historySynchronized = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true), "supportedCreationSettings": .array(["model", "effort", "approvalPolicy", "collaborationMode"].map(JSONValue.string)), "supportsDirectCreation": .bool(true), "supportsCreationReferences": .bool(true)])
    }
    func run() async {
        guard !started else { return }; started = true
        try? await Task.sleep(for: .seconds(2))
        var result: [String: Bool] = [:]
        let a = model.scope + "\nnew"
        model.draftStore.settings[a] = .object(["model": .string("gpt-5.5"), "effort": .string("high"), "approvalPolicy": .string("never"), "collaborationMode": .object(["mode": .string("plan"), "settings": .object(["model": .string("gpt-5.5"), "reasoning_effort": .string("high"), "developer_instructions": .null])])])
        model.draftStore.texts[a] = "\u{fffc}\u{fffc}"
        model.draftStore.skills[a] = [.init(name: "code-review", path: "/fixture/SKILL.md", offset: 0, displayName: "Review", iconData: "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGElEQVR4nGNgaPj/nyI8asCoAaMGDBcDAIHifh+5bmkmAAAAAElFTkSuQmCC"), .init(name: "Calendar", path: "app://calendar", offset: 1)]
        try? await Task.sleep(for: .milliseconds(300))
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) else { return }
        func editor(_ view: UIView) -> UITextView? { if let text = view as? UITextView { return text }; return view.subviews.lazy.compactMap(editor).first }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("creationrefs.png"))
        result["nativeRasterDecoded"] = ReferenceIcon.image(model.draftStore.skills[a]?.first?.iconData)?.cgImage?.width == 16
        result["inlineReferencesVisible"] = editor(window)?.accessibilityValue == "ReviewCalendar"
        let validSettings = model.draftStore.settings[a]!
        model.draftStore.settings[a] = validSettings.setting("model", .string("retired-model"))
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(200))
        result["unavailableModelPreventsCreate"] = MockTransport.store.all().filter { $0["path"] as? String == "/api/threads" }.isEmpty && model.draftStore.settings[a]?["model"].text == "retired-model"
        model.draftStore.settings[a] = validSettings.setting("effort", .string("unsupported"))
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(200))
        result["unavailableEffortPreventsCreate"] = MockTransport.store.all().filter { $0["path"] as? String == "/api/threads" }.isEmpty && model.draftStore.skills[a]?.count == 2
        model.draftStore.settings[a] = validSettings
        MockTransport.store.configureModels(delay: 0.5)
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.models"), object: nil)
        try? await Task.sleep(for: .milliseconds(100))
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(100))
        result["catalogRefreshBlocksExplicitModel"] = MockTransport.store.all().filter { $0["path"] as? String == "/api/threads" }.isEmpty && model.draftStore.settings[a] == validSettings
        try? await Task.sleep(for: .milliseconds(500))
        MockTransport.store.configureModels(delay: 0)
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.submit"), object: nil)
        try? await Task.sleep(for: .seconds(2))
        let writes = MockTransport.store.all().filter { $0["path"] as? String == "/api/threads" }
        let body = writes.last?["body"] as? [String: Any] ?? [:]
        let settings = body["settings"] as? [String: Any] ?? [:]
        result["firstTurnConfiguration"] = settings["approvalPolicy"] as? String == "never" && (settings["collaborationMode"] as? [String: Any])?["mode"] as? String == "plan"
        result["failedCreatePreservesConfiguration"] = model.draftStore.settings[a]?["approvalPolicy"].text == "never"
        result["referenceOnlyBody"] = body["prompt"] as? String == "" && (body["skills"] as? [[String: String]]) == [["name": "code-review", "path": "/fixture/SKILL.md"]] && (body["mentions"] as? [[String: String]]) == [["name": "Calendar", "path": "app://calendar"]]
        result["failedCreatePreservesDraft"] = model.draftStore.skills[a]?.count == 2 && model.draftStore.texts[a] == "\u{fffc}\u{fffc}"
        model.status = model.status.setting("supportsCreationReferences", .bool(false))
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(400))
        result["revokedNoWritePreservesDraft"] = MockTransport.store.all().filter { $0["path"] as? String == "/api/threads" }.count == writes.count && model.draftStore.skills[a]?.count == 2
        model.status = model.status.setting("supportsCreationReferences", .bool(true))
        guard let old = editor(window) else { return }
        let oldDelegate = old.delegate
        old.becomeFirstResponder(); old.setMarkedText("组合", selectedRange: NSRange(location: 2, length: 0))
        result["markedTextEstablished"] = old.markedTextRange != nil
        model.selectedDevice = "b"
        let b = model.scope + "\nnew"; model.draftStore.texts[b] = "B的草稿"; model.draftStore.skills[b] = []
        try? await Task.sleep(for: .milliseconds(500))
        result["scopeConfigurationIsolated"] = model.draftStore.settings[b] == nil && model.draftStore.settings[a]?["approvalPolicy"].text == "never"
        result["editorRecreated"] = editor(window) !== old
        old.text = "A迟到的输入"; oldDelegate?.textViewDidChange?(old)
        try? await Task.sleep(for: .milliseconds(200))
        result["lateCallbackCannotWriteB"] = model.draftStore.texts[b] == "B的草稿" && model.draftStore.skills[b]?.isEmpty == true
        model.draftStore.texts[b] = "unconfirmed create"
        MockTransport.store.configureModels(delay: 0, valid: false)
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.models"), object: nil)
        try? await Task.sleep(for: .milliseconds(200))
        for _ in 0..<2 { NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.submit"), object: nil); try? await Task.sleep(for: .milliseconds(500)) }
        let unknownWrites = MockTransport.store.all().filter { $0["path"] as? String == "/api/threads" && ($0["body"] as? [String: Any])?["prompt"] as? String == "unconfirmed create" }
        result["defaultModelSurvivesCatalogFailure"] = unknownWrites.count == 2 && model.draftStore.settings[b] == nil
        result["missingIdentityPreservesDraftAndRequest"] = unknownWrites.count == 2 && (unknownWrites.first?["body"] as? [String: Any])?["requestId"] as? String == (unknownWrites.last?["body"] as? [String: Any])?["requestId"] as? String && model.draftStore.texts[b] == "unconfirmed create" && model.selectedThread == nil
        model.draftStore.texts[b] = "confirmed create"
        NotificationCenter.default.post(name: Notification.Name("fixture.creationrefs.submit"), object: nil); try? await Task.sleep(for: .milliseconds(500))
        result["confirmedIdentityOpensCreatedThread"] = model.selectedThread?.id == "confirmed-native" && model.draftStore.texts[b] == ""
        result["passed"] = result.values.allSatisfy { $0 }
        var report: [String: Any] = result.mapValues { $0 as Any }; report["modelError"] = model.error ?? ""; report["confirmedThread"] = model.selectedThread?.id ?? ""; report["latestDraft"] = model.draftStore.texts[b] ?? ""; report["creationBodies"] = MockTransport.store.all().filter { $0["path"] as? String == "/api/threads" }
        try? JSONSerialization.data(withJSONObject: report).write(to: URL.documentsDirectory.appendingPathComponent("creationrefs-result.json"))
    }
}
