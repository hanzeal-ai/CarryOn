import SwiftUI
import CarryOnCore
import Foundation

@main struct ParityApp: App {
    @State private var fixture = ParityFixture()
    var body: some Scene {
        WindowGroup {
            Group {
                if fixture.phase == -1 { ProgressView() }
                else if fixture.phase == 0 { NewConversationView() }
                else if fixture.phase == 1 { ConversationChangesView(threadID: "fixture", scopedHistory: fixture.history) }
                else if fixture.phase == 2 { SkillsPickerView(target: .conversation(.init(scope: fixture.model.scope, threadID: "fixture"))) }
                else if fixture.phase == 4 { UnifiedDiffView(patch: fixture.diffPatch, filePath: "src/large.swift", wrapLines: fixture.diffWrap).padding(16) }
                else { ConversationGoalView(target: .init(scope: fixture.model.scope, threadID: "fixture")) }
            }.environment(fixture.model)
                .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidShowNotification)) { note in
                    fixture.keyboardHeight = (note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect)?.height ?? 0
                }.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.creation.modelsReady"))) { note in fixture.creationModelsReady = note.object as? Bool == true; if fixture.creationModelsReady && !fixture.creationProjectsReady { fixture.creationModelsIndependent = true } }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.creation.projectsReady"))) { note in fixture.creationProjectsReady = note.object as? Bool == true }
                .task { await fixture.run() }
        }
    }
}
private actor ReceiptSaveGate {
    private var blocked = false
    func block() { blocked = true }
    func write(_ snapshot: DraftSnapshot, to file: URL) async throws {
        if blocked { try await Task.sleep(for: .milliseconds(300)); throw APIError("fixture storage failure") }
        try LocalFiles.write(snapshot, to: file)
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
        func confirm(_ id: String) { lock.lock(); defer { lock.unlock() }; jobs[id]?["state"] = "accepted" }
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
                jobs[id] = ["id": id, "threadId": path.contains("side-chats") ? "side" : "fixture", "kind": path.hasSuffix("/compose") ? "message" : "operation:\(body["action"] ?? "")", "clientMessageId": id, "turnId": "turn-" + id, "state": (body["prompt"] as? String) == "uncertain" || (body["prompt"] as? String ?? "").hasSuffix("未知评论") ? "uncertain" : failed ? "failed" : path.hasSuffix("/compose") ? "accepted" : "completed", "error": failed ? "排队消息已变化" : ""]
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
        let data = try! JSONSerialization.data(withJSONObject: value)
        let deliver: @Sendable () -> Void = { [self] in
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }
        if (envelope["path"] as? String ?? "").hasPrefix("/api/projects") {
            DispatchQueue.global().asyncAfter(deadline: .now() + 5, execute: deliver)
        } else if ((envelope["body"] as? [String: Any])?["prompt"] as? String ?? "").contains("延时评论") {
            DispatchQueue.global().asyncAfter(deadline: .now() + 1, execute: deliver)
        } else { deliver() }
    }
    override func stopLoading() {}
}


@MainActor @Observable final class ParityFixture {
    let model = AppModel()
    var phase = -1
    var history: JSONValue = .null
    var diffPatch = ""
    var diffWrap = false
    private var started = false
    @ObservationIgnored var keyboardHeight: CGFloat = 0
    @ObservationIgnored var creationModelsReady = false
    @ObservationIgnored var creationModelsIndependent = false
    @ObservationIgnored var creationProjectsReady = false
    private func focusEditor(in view: UIView) -> Bool {
        if let editor = view as? UITextView, editor.isEditable, editor.accessibilityLabel == "询问 CarryOn" {
            return editor.becomeFirstResponder()
        }
        for child in view.subviews { if focusEditor(in: child) { return true } }
        return false
    }
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
        await model.draftStore.load(scope: model.scope)
        let creationKey = model.scope + "\nnew"
        model.draftStore.texts[creationKey] = ""
        model.draftStore.images[creationKey] = []
        model.draftStore.skills[creationKey] = []
        model.draftStore.comments[creationKey] = []
        model.draftStore.settings[creationKey] = .null
        model.authenticated = true; model.connected = true; model.historySynchronized = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true), "supportedCreationSettings": .array(["collaborationMode", "approvalPolicy"].map(JSONValue.string))])
        phase = 0
        try? await Task.sleep(for: .seconds(2))
        let modelsReadyBeforeProjects = creationModelsIndependent
        for _ in 0..<60 { if creationProjectsReady { break }; try? await Task.sleep(for: .milliseconds(100)) }
        model.draftStore.settings[creationKey] = .object(["model": .string("gpt-5.5"), "effort": .string("high")])
        try? await Task.sleep(for: .milliseconds(500)); capture("parity-new")
        model.draftStore.texts[creationKey] = "请检查这个项目"
        let creationWindow = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow)
        let editorFocused = creationWindow.map { focusEditor(in: $0) } ?? false
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
        let patch = "@@ -1,2 +1,3 @@\n let value = 1\n-old()\n+new(" + String(repeating: "long_diff_argument, ", count: 30) + ")\n+verify()"
        let change: JSONValue = .object(["path": .string("src/example.swift"), "diff": .string(patch)])
        let entry: JSONValue = .object(["id": .string("change"), "type": .string("fileChange"), "status": .string("completed"), "data": .object(["changes": .array([change])])])
        history = .object(["thread": .object(["id": .string("fixture")]), "timeline": .array([entry])])
        let scope = model.scope, key = scope + "\nfixture"
        model.draftStore.texts[key] = "保留已有草稿"; model.draftStore.images[key] = ["fixture-image"]
        model.draftStore.comments[key] = []
        model.selectedThread = try! Record(.object(["id": .string("fixture"), "title": .string("CarryOn")]))
        phase = 1; try? await Task.sleep(for: .seconds(1)); capture("parity-diff")
        func diffFrame(_ view: UIView) -> CGRect? {
            if view.accessibilityIdentifier == "fixture-diff-line-3" { return view.bounds }
            return view.subviews.lazy.compactMap(diffFrame).first
        }
        let window = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows).first { $0.isKeyWindow }
        func diffScroll(_ view: UIView) -> UIScrollView? {
            if view.accessibilityIdentifier?.hasPrefix("fixture-diff-line-") == true {
                var parent = view.superview
                while let node = parent { if let scroll = node as? UIScrollView { return scroll }; parent = node.superview }
            }
            return view.subviews.lazy.compactMap(diffScroll).first
        }
        let beforeWrap = window.flatMap(diffFrame)
        let beforeScroll = window.flatMap(diffScroll)
        let beforeScrollWidth = beforeScroll?.contentSize.width ?? 0
        let beforeScrollHeight = beforeScroll?.bounds.height ?? 0
        NotificationCenter.default.post(name: Notification.Name("fixture.wrapDiff"), object: nil)
        try? await Task.sleep(for: .milliseconds(600)); capture("parity-diff-wrap")
        let afterWrap = window.flatMap(diffFrame)
        let afterScroll = window.flatMap(diffScroll)
        let wrappedScrollWidth = afterScroll?.contentSize.width ?? 0
        let wrappedViewportWidth = afterScroll?.bounds.width ?? 0
        let diffWraps = beforeWrap != nil && afterWrap != nil && afterWrap!.height > beforeWrap!.height + 20 && afterWrap!.width <= beforeWrap!.width + 1 && wrappedScrollWidth <= wrappedViewportWidth + 1
        let diffViewportExpands = (afterScroll?.bounds.height ?? 0) > beforeScrollHeight + 20
        let diffHorizontalReadable = beforeScrollWidth > wrappedViewportWidth + 20
        NotificationCenter.default.post(name: Notification.Name("fixture.wrapDiff"), object: nil)
        try? await Task.sleep(for: .milliseconds(600))
        let restoredWrap = window.flatMap(diffFrame)
        let diffUnwraps = beforeWrap != nil && restoredWrap != nil && abs(beforeWrap!.height - restoredWrap!.height) < 1 && abs(beforeWrap!.width - restoredWrap!.width) < 1
        let initialHistory = history
        let shortChange = change.setting("diff", .string("@@ -1 +1 @@\n-old()\n+new()"))
        history = history.setting("timeline", .array([entry.setting("data", .object(["changes": .array([shortChange])]))]))
        try? await Task.sleep(for: .milliseconds(600))
        let updatedScroll = window.flatMap(diffScroll)
        let scopedDiffUpdates = (updatedScroll?.contentSize.width ?? 0) > 0 && (updatedScroll?.contentSize.width ?? 0) <= (updatedScroll?.bounds.width ?? 0) + 1
        history = initialHistory
        try? await Task.sleep(for: .milliseconds(600))
        NotificationCenter.default.post(name: Notification.Name("fixture.comment"), object: nil)
        try? await Task.sleep(for: .milliseconds(700)); capture("parity")
        model.selectedDevice = "other"
        NotificationCenter.default.post(name: Notification.Name("fixture.submitComment"), object: nil)
        let scoped = model.draftStore.texts[key] == "保留已有草稿" && model.draftStore.texts[model.scope + "\nfixture"] == nil && model.draftStore.comments[key, default: []].isEmpty && model.draftStore.comments[model.scope + "\nfixture"] == nil
        model.selectedDevice = "fixture"
        NotificationCenter.default.post(name: Notification.Name("fixture.submitComment"), object: nil)
        try? await Task.sleep(for: .milliseconds(200))
        let draft = model.draftStore.texts[key] ?? ""
        let notes = model.draftStore.comments[key] ?? []
        let appended = draft == "保留已有草稿" && notes.count == 1 && notes[0].sourceID == "change" && notes[0].location == "R2" && notes[0].prompt.contains("请检查这里的边界")
        capture("parity-local-comment")
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
        diffPatch = patch; phase = 4
        try? await Task.sleep(for: .milliseconds(600))
        let longWidth = window.flatMap(diffScroll)?.contentSize.width ?? 0
        diffPatch = "@@ -1 +1 @@\n-old()\n+new()"
        try? await Task.sleep(for: .milliseconds(600))
        let shortScroll = window.flatMap(diffScroll)
        let shortWidth = shortScroll?.contentSize.width ?? 0
        let diffPatchResizes = longWidth > shortWidth + 20 && shortWidth > 0 && shortWidth <= (shortScroll?.bounds.width ?? 0) + 1
        func mountedDiffRows(_ view: UIView) -> Int {
            (view.accessibilityIdentifier?.hasPrefix("fixture-diff-line-") == true ? 1 : 0) + view.subviews.reduce(0) { $0 + mountedDiffRows($1) }
        }
        let frames = DiffFrameSampler(); frames.start()
        diffPatch = "@@ -1,1000 +1,1000 @@\n" + (0..<1000).map { " line_\($0) " + String(repeating: "argument, ", count: 6) }.joined(separator: "\n")
        try? await Task.sleep(for: .milliseconds(600))
        let longMounted = window.map(mountedDiffRows) ?? 0
        diffWrap = true
        try? await Task.sleep(for: .milliseconds(600))
        let wrappedMounted = window.map(mountedDiffRows) ?? 0
        let largeScroll = window.flatMap(diffScroll)
        frames.stop()
        let diffLazyRendering = longMounted > 0 && longMounted < 150 && wrappedMounted > 0 && wrappedMounted < 150 && (largeScroll?.contentSize.height ?? 0) > 10000 && (largeScroll?.bounds.height ?? 501) <= 500
        capture("parity-diff-large")
        let highlightPatch = "@@ -0,0 +1,2 @@\n+public enum Sample: String {\n+    case ready = \"ready👋你好\"\n"
        let colored = await CodeHighlight.shared.diff(highlightPatch, language: "swift", dark: false)
        let sourceRows = highlightPatch.components(separatedBy: "\n")
        let diffHighlightPreservesText = !colored.isEmpty && sourceRows.enumerated().allSatisfy { String((colored[$0.offset] ?? AttributedString($0.element)).characters) == $0.element }
        let colors = Set(colored.values.flatMap { $0.runs.compactMap { $0.uiKit.foregroundColor?.description } })
        let diffHighlightHasColors = colors.count > 1
        let diffHighlightKeepsTypography = colored.values.allSatisfy { $0.runs.allSatisfy { $0.uiKit.font == nil && $0.uiKit.paragraphStyle == nil && $0.uiKit.backgroundColor == nil } }
        let darkColored = await CodeHighlight.shared.diff(highlightPatch, language: "swift", dark: true)
        let darkColors = Set(darkColored.values.flatMap { $0.runs.compactMap { $0.uiKit.foregroundColor?.description } })
        let diffHighlightThemeChanges = darkColors != colors
        let isolatedPatch = "@@ -1,2 +1 @@\n-/* removed comment\n-closed */\n+let value = \"你好👋\"\n@@ -20 +20 @@\n-/* unfinished\n+let next = 2"
        let isolated = await CodeHighlight.shared.diff(isolatedPatch, language: "swift", dark: false)
        func foregrounds(_ value: AttributedString) -> [String] {
            value.runs.flatMap { run in Array(repeating: run.uiKit.foregroundColor?.description ?? "", count: String(value[run.range].characters).utf16.count) }
        }
        let expectedValue = await CodeHighlight.shared.render("let value = \"你好👋\"", language: "swift", dark: false)
        let expectedNext = await CodeHighlight.shared.render("let next = 2", language: "swift", dark: false)
        let diffHunksIsolate = isolated[0] == nil && isolated[4] == nil &&
            isolated[3].map { Array(foregrounds($0).dropFirst()) } == expectedValue.map(foregrounds) &&
            isolated[6].map { Array(foregrounds($0).dropFirst()) } == expectedNext.map(foregrounds) && isolated[3] != nil && isolated[6] != nil
        let markerPatch = "@@ -1,2 +1,3 @@\n /* common open\n-old */\n\\ No newline at end of file\n+new */\n+let next = 2"
        let markerColored = await CodeHighlight.shared.diff(markerPatch, language: "swift", dark: false)
        let expectedComment = await CodeHighlight.shared.render("/* common open\nnew */", language: "swift", dark: false)
        let diffNoNewlinePreservesState = markerColored[3] == nil && markerColored[4] != nil &&
            markerColored[4].map { Array(foregrounds($0).dropFirst()) } == expectedComment.map { Array(foregrounds($0).suffix("new */".utf16.count)) }
        let oversized = await CodeHighlight.shared.diff(String(repeating: "a", count: CodeDocument.highlightLimit + 1), language: "swift", dark: false)
        let diffHighlightBounded = oversized.isEmpty
        model.history = history.setting("status", .object(["state": .string("idle")]))
            .setting("access", .object(["nativeReady": .bool(true), "canInteract": .bool(true)]))
            .setting("controls", .object(["supportedOperations": .array([.string("queue-add")]), "supportsSkills": .bool(true), "supportsMentions": .bool(true)]))
        model.draft = ""
        model.draftSkills = []
        model.draftImages = []
        let commentOnlySent = await model.compose()
        let delivered = MockTransport.store.all().last { ($0["path"] as? String ?? "").hasSuffix("/compose") }
        let deliveredPrompt = (delivered?["body"] as? [String: Any])?["prompt"] as? String ?? ""
        let commentOnlyDelivery = commentOnlySent && deliveredPrompt.contains("src/example.swift（R2）") && deliveredPrompt.contains("请检查这里的边界") && model.draftComments.isEmpty
        let line = UnifiedDiff.lines(patch).first { $0.location == "R2" }!
        let queued = ReviewComment(sourceID: "change", path: "src/example.swift", patch: patch, line: line, text: "排队评论")!
        model.draftComments = [queued]
        model.history = model.history.setting("status", .object(["state": .string("running")])).setting("queue", .object(["fingerprint": .string("fixture-queue"), "messages": .array([])]))
        let queuedSent = await model.compose(queueFollowUp: true)
        let queueBody = MockTransport.store.all().last { ($0["path"] as? String ?? "").hasSuffix("/operations") }?["body"] as? [String: Any] ?? [:]
        let commentQueueDelivery = queuedSent && queueBody["action"] as? String == "queue-add" && (queueBody["prompt"] as? String ?? "").contains("排队评论") && model.draftComments.isEmpty
        model.history = model.history.setting("status", .object(["state": .string("idle")]))
        let unknown = ReviewComment(sourceID: "change", path: "src/example.swift", patch: patch, line: line, text: "未知评论")!
        model.draftComments = [unknown]
        let unknownSent = await model.compose()
        let writesBeforeQuery = MockTransport.store.all().filter { ($0["path"] as? String ?? "").hasSuffix("/compose") }.count
        if let outgoing = model.outgoing.values.first(where: { $0["state"].text == "uncertain" }) { await model.checkOutgoing(outgoing) }
        let unknownCommentsRetained = !unknownSent && model.draftComments == [unknown] && MockTransport.store.all().filter { ($0["path"] as? String ?? "").hasSuffix("/compose") }.count == writesBeforeQuery
        let unknownItem = model.outgoing.values.first { $0["state"].text == "uncertain" }!
        MockTransport.store.confirm(unknownItem["id"].text)
        await model.checkOutgoing(unknownItem)
        let retryAfterConfirmation = await model.compose()
        let queriedCommentsCleared = model.draftComments.isEmpty && !retryAfterConfirmation && MockTransport.store.all().filter { ($0["path"] as? String ?? "").hasSuffix("/compose") }.count == writesBeforeQuery
        let anotherUnknown = ReviewComment(sourceID: "change", path: "src/example.swift", patch: patch, line: line, text: "再次未知评论")!
        model.draftComments = [anotherUnknown]
        _ = await model.compose()
        let anotherItem = model.outgoing.values.first { $0["state"].text == "uncertain" }!
        var later = anotherUnknown; later.text = "核对前修改"
        let laterAdded = ReviewComment(sourceID: "change", path: "src/example.swift", patch: patch, line: line, text: "核对前新增")!
        model.draftComments = [later, laterAdded]
        let beforeSecondQuery = MockTransport.store.all().filter { ($0["path"] as? String ?? "").hasSuffix("/compose") }.count
        MockTransport.store.confirm(anotherItem["id"].text)
        await model.checkOutgoing(anotherItem)
        let queriedEditsRetained = model.draftComments == [later, laterAdded] && MockTransport.store.all().filter { ($0["path"] as? String ?? "").hasSuffix("/compose") }.count == beforeSecondQuery
        let delayed = ReviewComment(sourceID: "change", path: "src/example.swift", patch: patch, line: line, text: "延时评论\u{fffc}")!
        model.draftComments = [delayed]
        let waiting = Task { await model.compose() }
        for _ in 0..<100 {
            if MockTransport.store.all().contains(where: { (($0["body"] as? [String: Any])?["prompt"] as? String ?? "").contains("延时评论") }) { break }
            try? await Task.sleep(for: .milliseconds(10))
        }
        var edited = delayed; edited.text = "等待期间修改"
        let added = ReviewComment(sourceID: "change", path: "src/example.swift", patch: patch, line: line, text: "等待期间新增")!
        model.draftComments = [edited, added]
        let confirmed = await waiting.value
        let commentEditsRetained = MockTransport.store.all().contains { (($0["body"] as? [String: Any])?["prompt"] as? String ?? "").contains("延时评论\u{fffc}") } && confirmed && model.draftComments == [edited, added]
        // Duplicate partial live receipts must not release the ID before a failed durable save.
        let originalStore = model.draftStore, storageGate = ReceiptSaveGate()
        model.draftStore = DraftStore(file: URL.documentsDirectory.appendingPathComponent("receipt-failure-" + UUID().uuidString + ".json"), write: { snapshot, file in
            try await storageGate.write(snapshot, to: file)
        }) { _, _ in }
        await model.draftStore.load(scope: model.scope)
        let storageUnknown = ReviewComment(sourceID: "change", path: "src/example.swift", patch: patch, line: line, text: "保存失败未知评论")!
        model.draftComments = [storageUnknown]
        _ = await model.compose()
        let storageItem = model.outgoing.values.first { $0["prompt"].text.hasSuffix("保存失败未知评论") }!
        await storageGate.block()
        let partial: JSONValue = .object(["id": storageItem["id"], "threadId": .string("fixture"), "state": .string("accepted")])
        model.reconcile([partial]); model.reconcile([partial])
        try? await Task.sleep(for: .milliseconds(700))
        let retainedID = try! model.pending.requestID(scope: model.scope, target: "fixture", path: "/api/threads/fixture/compose", body: .object(["prompt": .string(storageUnknown.prompt)]))
        let storageSaved = await model.draftStore.flush()
        let liveReceiptStorageFailureRetainsID = retainedID == storageItem["id"].text && !storageSaved
        model.draftStore = originalStore
        let result: [String: Any] = ["creationModelsIndependent": modelsReadyBeforeProjects, "creationCatalogsLoaded": creationModelsReady && creationProjectsReady, "creationEditorFocused": editorFocused, "creationKeyboardHeight": keyboardHeight, "passed": modelsReadyBeforeProjects && creationModelsReady && creationProjectsReady && scoped && appended && noSend && imagesRetained && diffWraps && diffUnwraps && diffViewportExpands && diffHorizontalReadable && diffPatchResizes && diffLazyRendering && scopedDiffUpdates && diffHighlightPreservesText && diffHighlightHasColors && diffHighlightKeepsTypography && diffHighlightThemeChanges && diffHighlightBounded && diffHunksIsolate && diffNoNewlinePreservesState && commentOnlyDelivery && commentQueueDelivery && unknownCommentsRetained && commentEditsRetained && queriedCommentsCleared && queriedEditsRetained && liveReceiptStorageFailureRetainsID, "liveReceiptStorageFailureRetainsID": liveReceiptStorageFailureRetainsID, "queriedCommentsCleared": queriedCommentsCleared, "queriedEditsRetained": queriedEditsRetained, "commentOnlyDelivery": commentOnlyDelivery, "commentQueueDelivery": commentQueueDelivery, "unknownCommentsRetained": unknownCommentsRetained, "commentEditsRetained": commentEditsRetained, "diffHighlightPreservesText": diffHighlightPreservesText, "diffHighlightHasColors": diffHighlightHasColors, "diffLightColors": colors.sorted(), "diffDarkColors": darkColors.sorted(), "diffHighlightKeepsTypography": diffHighlightKeepsTypography, "diffHighlightThemeChanges": diffHighlightThemeChanges, "diffHighlightBounded": diffHighlightBounded, "diffHunksIsolate": diffHunksIsolate, "diffNoNewlinePreservesState": diffNoNewlinePreservesState, "scopedDiffUpdates": scopedDiffUpdates, "diffLazyRendering": diffLazyRendering, "diffMountedRows": longMounted, "diffWrappedMountedRows": wrappedMounted, "diffMaxFrameGapMs": frames.maxGapMs, "diffSampledFrames": frames.times.count, "diffPatchResizes": diffPatchResizes, "diffShortPatchWidth": shortWidth, "diffWraps": diffWraps, "diffViewportExpands": diffViewportExpands, "diffHorizontalReadable": diffHorizontalReadable, "diffBeforeScrollWidth": beforeScrollWidth, "diffWrappedScrollWidth": wrappedScrollWidth, "diffViewportWidth": wrappedViewportWidth, "diffUnwraps": diffUnwraps, "diffBeforeWidth": beforeWrap?.width ?? 0, "diffWrappedWidth": afterWrap?.width ?? 0, "diffWrappedHeight": afterWrap?.height ?? 0, "scopeIsolation": scoped, "commentAppended": appended, "noAutomaticSend": noSend, "imagesRetained": imagesRetained]
        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("parity-result.json"))
    }
}

@MainActor private final class DiffFrameSampler: NSObject {
    private var link: CADisplayLink?
    var times: [Double] = []
    var maxGapMs: Double { zip(times, times.dropFirst()).map { ($0.1 - $0.0) * 1000 }.max() ?? 0 }
    func start() { link = CADisplayLink(target: self, selector: #selector(sample)); link?.add(to: .main, forMode: .common) }
    func stop() { link?.invalidate(); link = nil }
    @objc private func sample(_ sender: CADisplayLink) { times.append(CACurrentMediaTime()) }
}
