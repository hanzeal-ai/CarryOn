import SwiftUI
import CarryOnCore

@main struct ConversationVisualApp: App {
    @State private var fixture = ConversationVisualFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack { ConversationView(thread: fixture.thread) }
                .environment(fixture.model).task { await fixture.capture() }
        }
    }
}
private final class VisualSideState: @unchecked Sendable {
    let lock = NSLock()
    private var creates = 0
    private var sends = 0
    private var operations: [String] = []
    private var prompts: [String] = []
    private var settingsWrites: [JSONValue] = []
    func operation(_ action: String, settings: JSONValue) { lock.withLock { operations.append(action); if action == "settings" { settingsWrites.append(settings) } } }
    var settings: [JSONValue] { lock.withLock { settingsWrites } }
    func compose(_ prompt: String) { lock.withLock { prompts.append(prompt) } }
    var commands: ([String], [String]) { lock.withLock { (operations, prompts) } }
    func create() { lock.withLock { creates += 1 } }
    func send() { lock.withLock { sends += 1 } }
    var counts: (Int, Int) { lock.withLock { (creates, sends) } }
}
private final class ConversationVisualTransport: URLProtocol, @unchecked Sendable {
    static let state = VisualSideState()
    static let sideID = "22222222-2222-4222-8222-222222222222"
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var response: [String: Any] = ["threads": [], "total": 0, "events": [], "nextSequence": 0, "models": [["id": "gpt-5.5", "name": "GPT-5.5", "efforts": ["high"], "defaultEffort": "high"]]]
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; bytes.append(buffer, count: count) }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let path = String((envelope["path"] as? String ?? request.url!.path).split(separator: "?", maxSplits: 1).first ?? "")
        let body = envelope["body"] as? [String: Any] ?? [:]
        if path.hasSuffix("/operations") {
            let value = try! JSONDecoder().decode(JSONValue.self, from: JSONSerialization.data(withJSONObject: body))
            Self.state.operation(body["action"] as? String ?? "", settings: value["settings"])
            response = ["id": body["requestId"] ?? "", "state": "completed"]
        } else if path.hasSuffix("/compose"), !path.contains("/side-chats/") {
            Self.state.compose(body["prompt"] as? String ?? "")
            response = ["id": body["requestId"] ?? "", "state": "accepted"]
        } else if path.hasSuffix("/side-chats"), envelope["method"] as? String == "POST" {
            Self.state.create()
            response = ["id": body["requestId"] ?? "", "state": "completed", "createdThreadId": Self.sideID, "parentId": "11111111-1111-4111-8111-111111111111"]
        } else if path.hasSuffix("/side-chats") {
            response = ["chats": Self.state.counts.0 > 0 ? [["id": Self.sideID, "title": "临时聊天", "parentId": "11111111-1111-4111-8111-111111111111"]] : [], "scanning": false]
        } else if path.contains("/side-chats/"), path.hasSuffix("/history") {
            response = ["thread": ["id": Self.sideID], "status": ["state": "idle"], "controls": ["supportedOperations": ["compose", "close"], "settings": [:]], "timeline": []]
        } else if path.contains("/side-chats/"), path.hasSuffix("/compose") {
            Self.state.send(); response = ["state": "accepted"]
        }
        let data = try! JSONSerialization.data(withJSONObject: response)
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
@MainActor @Observable private final class ConversationVisualFixture {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("11111111-1111-4111-8111-111111111111"), "title": .string("优化移动端体验")]))
    private var captured = false
    init() {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ConversationVisualTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://conversation-visual.invalid"), configuration: config))
        model.addressText = "https://conversation-visual.invalid"; model.selectedDevice = "fixture-device"
        model.devices = [try! Record(.object(["id": .string("fixture-device"), "online": .bool(true), "permissions": .array(["view", "send", "edit", "stop", "create", "files"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.foreground = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.selectedThread = thread
        let raw = """
        {"thread":{"id":"11111111-1111-4111-8111-111111111111"},"status":{"state":"idle"},"runtime":{"type":"idle"},"access":{"canInteract":true,"nativeReady":true},"source":"desktop-snapshot","controls":{"supportedOperations":["settings","side-create","voice-start","voice-stop"],"supportedSettings":["model","effort","collaborationMode","approvalPolicy"],"settings":{"model":"gpt-5.5","effort":"high","approvalPolicy":"on-request"},"requests":[]},"metadata":{"latestTokenUsageInfo":{"last":{"totalTokens":16000},"modelContextWindow":64000}},"timeline":[{"id":"user","type":"userMessage","text":"检查移动端交互并说明修改结果"},{"id":"cmd","type":"commandExecution","status":"completed","data":{"command":"swift test","exitCode":0,"durationMs":1300,"aggregatedOutput":"All tests passed."}},{"id":"answer","type":"agentMessage","text":"已完成输入框和会话交互调整。 **粗体** *斜体* ~~删除~~ `代码` [链接](https://openai.com)。\\n\\n- 配置与模型选择分别提供入口\\n- 临时聊天保留独立草稿\\n- 原生上下文用量实时同步\\n\\n你可以选择这段文字，在临时聊天中继续讨论。"}]}
        """
        model.history = try! JSONDecoder().decode(JSONValue.self, from: Data(raw.utf8))
        var entries = model.history["timeline"].array
        for index in 1...6 {
            entries.insert(.object([
                "id": .string("tool-\(index)"), "type": .string("mcpToolCall"),
                "status": .string(index == 6 ? "failed" : "completed"),
                "data": .object(["server": .string("fixture"), "tool": .string("inspect_\(index)"),
                    "arguments": .object(["index": .number(Double(index))]),
                    "result": .object(["content": .array([.object(["type": .string("text"), "text": .string("工具 \(index) 输出：" + String(repeating: "可换行的长文本输出。", count: 12))])])])
                ])
            ]), at: entries.count - 1)
        }
        model.history = model.history.setting("timeline", .array(entries))
        model.historySynchronized = true; model.historyRevision += 1
        model.draft = "使用 \u{fffc} 检查交互，然后说明结果。"
        model.draftSkills = [ComposerReference(name: "Review", path: "/fixture/SKILL.md", offset: 3)]
    }
    func capture() async {
        guard !captured else { return }; captured = true
        try? await Task.sleep(for: .seconds(3))
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("conversationvisual.png"))
        var results: [String: Bool] = [:]
        var comparisonLines: [String] = []
        var compactDiagnostics: [String: Any] = [:]
        func textViews(_ view: UIView) -> [UITextView] {
            (view as? UITextView).map { [$0] } ?? view.subviews.flatMap(textViews)
        }
        // Measure a settled layout, not an interpolated animation frame.
        func settledWidth(_ editor: UITextView?) async -> CGFloat? {
            guard let editor else { return nil }
            var previous: CGFloat = -1, stableSamples = 0
            for _ in 0..<40 {
                try? await Task.sleep(for: .milliseconds(50))
                let width = editor.bounds.width
                stableSamples = width > 0 && abs(width - previous) < 0.01 ? stableSamples + 1 : 0
                if stableSamples >= 4 { return width }
                previous = width
            }
            return nil
        }

        let savedDraft = model.draft, savedReferences = model.draftSkills
        model.draft = ""; model.draftSkills = []
        try? await Task.sleep(for: .milliseconds(350))
        let compactEditor = textViews(window).first { $0.accessibilityIdentifier == "carryon-composer-editor" && $0.isEditable }
        let compactWidth = await settledWidth(compactEditor) ?? 0
        let compactImage = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? compactImage.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("phone-compact-composer.png"))
        compactEditor?.becomeFirstResponder()
        try? await Task.sleep(for: .milliseconds(350))
        let expandedEditor = textViews(window).first { $0.accessibilityIdentifier == "carryon-composer-editor" && $0.isEditable }
        let expandedWidth = await settledWidth(expandedEditor) ?? 0
        results["compactExpansionKeepsEditorAndFocus"] = compactEditor != nil && expandedEditor === compactEditor && expandedEditor?.isFirstResponder == true
        results["expandedEditorGainsHorizontalSpace"] = compactWidth > 0 && expandedWidth > compactWidth
        expandedEditor?.insertText("验证输入不会丢失")
        try? await Task.sleep(for: .milliseconds(150))
        results["expandedInputUpdatesExistingDraft"] = model.draft == "验证输入不会丢失" && expandedEditor?.isFirstResponder == true
        expandedEditor?.resignFirstResponder(); model.draft = ""
        // Keyboard dismissal and the composer animation settle asynchronously.
        // Keep the width assertion; wait for its visible result within a bounded deadline.
        for _ in 0..<20 {
            try? await Task.sleep(for: .milliseconds(50))
            if compactEditor?.isFirstResponder == false && abs((compactEditor?.bounds.width ?? 0) - compactWidth) < 1 { break }
        }
        results["emptyBlurRestoresCompactLayout"] = compactEditor?.isFirstResponder == false && abs((compactEditor?.bounds.width ?? 0) - compactWidth) < 1
        compactDiagnostics = ["beforeWidth": compactWidth, "expandedWidth": expandedWidth, "afterWidth": compactEditor?.bounds.width ?? 0,
                              "focusedAfterBlur": compactEditor?.isFirstResponder ?? false, "draftAfterBlur": model.draft,
                              "referenceCount": model.draftSkills.count]
        let blurredImage = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? blurredImage.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("phone-blurred-composer.png"))
        model.draft = savedDraft; model.draftSkills = savedReferences
        try? await Task.sleep(for: .milliseconds(150))

        let comparisonDraft = model.draft, comparisonReferences = model.draftSkills
        model.draft = "Use \u{fffc} to make a Codex remote app that use the app server. Make a \u{fffc} companion app. Use \u{fffc} and make sure the code is tight."
        let icon = UIGraphicsImageRenderer(size: CGSize(width: 48, height: 48)).image { _ in
            UIColor.systemBlue.setFill(); UIBezierPath(roundedRect: CGRect(x: 0, y: 0, width: 48, height: 48), cornerRadius: 9).fill()
            UIImage(systemName: "chevron.left.forwardslash.chevron.right")?.withTintColor(.white, renderingMode: .alwaysOriginal).draw(in: CGRect(x: 8, y: 8, width: 32, height: 32))
        }.pngData()?.base64EncodedString()
        let offsets = (model.draft as NSString).length > 0 ? Array(model.draft.utf16.enumerated().filter { $0.element == 0xfffc }.map(\.offset)) : []
        model.draftSkills = zip(["Build iOS Apps", "Build macOS Apps", "Finalize Code"], offsets).enumerated().map { index, pair in
            ComposerReference(name: "comparison-\(index)", path: "/fixture/\(index)/SKILL.md", offset: pair.1, displayName: pair.0, iconData: index < 2 ? icon : nil)
        }
        try? await Task.sleep(for: .milliseconds(300))
        let comparisonEditor = textViews(window).first { $0.isEditable && $0.text.contains("Codex remote") }
        comparisonEditor?.becomeFirstResponder()
        try? await Task.sleep(for: .milliseconds(500))
        results["officialComposerComparisonHasThreeInlineReferences"] = comparisonEditor.map { editor in
            var count = 0
            editor.attributedText.enumerateAttribute(.attachment, in: NSRange(location: 0, length: editor.attributedText.length)) { value, _, _ in if value != nil { count += 1 } }
            return count == 3 && editor.isFirstResponder && editor.markedTextRange == nil
        } == true
        if let editor = comparisonEditor {
            let manager = editor.layoutManager
            manager.ensureLayout(for: editor.textContainer)
            let glyphs = manager.glyphRange(for: editor.textContainer)
            manager.enumerateLineFragments(forGlyphRange: glyphs) { _, _, _, range, _ in
                let characters = manager.characterRange(forGlyphRange: range, actualGlyphRange: nil)
                comparisonLines.append((editor.attributedText.string as NSString).substring(with: characters).trimmingCharacters(in: .whitespacesAndNewlines))
            }
            if editor.traitCollection.preferredContentSizeCategory == .large {
                let endings = ["Codex remote", "Make a", "app. Use", "code is tight."]
                results["officialComposerFourLineEndings"] = comparisonLines.count == 4 && zip(comparisonLines, endings).allSatisfy { $0.0.hasSuffix($0.1) }
            }
        }
        let comparisonImage = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? comparisonImage.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("official-composer-comparison.png"))
        try? Data().write(to: URL.documentsDirectory.appendingPathComponent("official-composer-keyboard.capture"))
        try? await Task.sleep(for: .milliseconds(800))
        comparisonEditor?.resignFirstResponder(); model.draft = comparisonDraft; model.draftSkills = comparisonReferences
        try? await Task.sleep(for: .milliseconds(300))

        let originalHistory = model.history, originalDevices = model.devices, originalDraft = model.draft, originalReferences = model.draftSkills
        model.history = originalHistory.setting("controls", originalHistory["controls"].setting("supportedOperations", .array(["settings", "compact", "fork", "side-create"].map(JSONValue.string))))
        func permissions(_ values: [String]) {
            model.devices = [try! Record(originalDevices[0].value.setting("permissions", .array(values.map(JSONValue.string))))]
        }
        model.draftSkills = []; permissions(["view", "edit"]); model.draft = "/compact"
        try? await Task.sleep(for: .milliseconds(150))
        results["editOnlyCommandEditable"] = textViews(window).contains { $0.text == "/compact" && $0.isEditable }
        NotificationCenter.default.post(name: Notification.Name("fixture.command.submit"), object: nil)
        for _ in 0..<30 { try? await Task.sleep(for: .milliseconds(50)); if ConversationVisualTransport.state.commands.0.contains("compact") { break } }
        results["editOnlyCompactExecuted"] = ConversationVisualTransport.state.commands.0 == ["compact"]
        permissions(["view", "create"]); model.draft = "/fork"
        try? await Task.sleep(for: .milliseconds(150))
        results["createOnlyCommandEditable"] = textViews(window).contains { $0.text == "/fork" && $0.isEditable }
        results["createOnlyForkAvailable"] = ConversationCommands.available("fork", model: model, target: .init(scope: model.scope, threadID: thread.id))
        permissions(["view", "send", "edit"]); model.draft = "/plan /fork"
        NotificationCenter.default.post(name: Notification.Name("fixture.command.submit"), object: nil)
        for _ in 0..<30 { try? await Task.sleep(for: .milliseconds(50)); if !ConversationVisualTransport.state.commands.1.isEmpty { break } }
        results["planArgumentIsLiteral"] = ConversationVisualTransport.state.commands.0 == ["compact", "settings"] && ConversationVisualTransport.state.commands.1 == ["/fork"]
        permissions(["view", "edit"])
        let planSettings: JSONValue = .object(["model": .string("gpt-5.5"), "effort": .string("high"), "collaborationMode": .object(["mode": .string("plan"), "settings": .object(["developer_instructions": .string("keep")])])])
        model.history = model.history.setting("controls", model.history["controls"].setting("settings", planSettings))
        model.draft = "/plan"
        NotificationCenter.default.post(name: Notification.Name("fixture.command.submit"), object: nil)
        for _ in 0..<30 { try? await Task.sleep(for: .milliseconds(50)); if ConversationVisualTransport.state.settings.count == 2 && model.draft.isEmpty { break } }
        results["barePlanDisables"] = ConversationVisualTransport.state.settings.last?["collaborationMode"]["mode"].text == "default"
        results["planTogglePreservesSettings"] = ConversationVisualTransport.state.settings.last?["collaborationMode"]["settings"] == .object(["model": .string("gpt-5.5"), "reasoning_effort": .string("high"), "developer_instructions": .string("keep")])
        model.history = model.history.setting("controls", model.history["controls"].setting("settings", planSettings.setting("collaborationMode", planSettings["collaborationMode"].setting("mode", .string("default")))))
        model.draft = "/plan"
        NotificationCenter.default.post(name: Notification.Name("fixture.command.submit"), object: nil)
        for _ in 0..<30 { try? await Task.sleep(for: .milliseconds(50)); if ConversationVisualTransport.state.settings.count == 3 && model.draft.isEmpty { break } }
        results["barePlanEnables"] = ConversationVisualTransport.state.settings.last?["collaborationMode"]["mode"].text == "plan"
        results["planToggleDoesNotSend"] = ConversationVisualTransport.state.commands.1 == ["/fork"]
        model.devices = originalDevices; model.history = originalHistory; model.draft = originalDraft; model.draftSkills = originalReferences
        try? await Task.sleep(for: .milliseconds(150))
        let views = textViews(window)
        let rich = views.first { $0.text.contains("粗体") }
        func font(_ text: String) -> UIFont? {
            guard let rich else { return nil }; let range = (rich.text as NSString).range(of: text)
            return range.location == NSNotFound ? nil : rich.attributedText.attribute(.font, at: range.location, effectiveRange: nil) as? UIFont
        }
        results["bold"] = font("粗体")?.fontDescriptor.symbolicTraits.contains(.traitBold) == true
        results["italic"] = font("斜体")?.fontDescriptor.symbolicTraits.contains(.traitItalic) == true
        if let rich {
            results["strike"] = rich.attributedText.attribute(.strikethroughStyle, at: (rich.text as NSString).range(of: "删除").location, effectiveRange: nil) != nil
            results["link"] = rich.attributedText.attribute(.link, at: (rich.text as NSString).range(of: "链接").location, effectiveRange: nil) as? URL == URL(string: "https://openai.com")
        }
        if let view = views.first(where: { $0.text.hasPrefix("你可以选择") }),
           let menu = view.delegate?.textView?(view, editMenuForTextIn: NSRange(location: 0, length: 5), suggestedActions: []),
           let add = menu.children.compactMap({ $0 as? UIAction }).first(where: { $0.title == "添加到聊天" }) {
            let originalAnnotations = model.draftAnnotations, originalText = model.draft
            let button = UIButton(); button.addAction(add, for: .touchUpInside)
            button.sendActions(for: .touchUpInside)
            results["bodySelectionCreatesAnnotationWithoutSending"] = model.draftAnnotations.count == originalAnnotations.count + 1 && model.draftAnnotations.last?.text == (view.text as NSString).substring(with: NSRange(location: 0, length: 5)) && model.draft == originalText && ConversationVisualTransport.state.counts == (0, 0)
            let captured = model.draftAnnotations
            try? await Task.sleep(for: .milliseconds(350))
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("annotation-chip.png"))
            model.selectedThread = try! Record(.object(["id": .string("other"), "title": .string("other")]))
            button.sendActions(for: .touchUpInside)
            results["staleAnnotationMenuCannotMutateOtherDraft"] = model.draftAnnotations.isEmpty
            model.selectedThread = thread
            model.devices = [try! Record(originalDevices[0].value.setting("permissions", .array([])))]
            button.sendActions(for: .touchUpInside)
            results["revokedAnnotationMenuCannotMutateDraft"] = model.draftAnnotations == captured
            model.devices = originalDevices; model.draftAnnotations = originalAnnotations
        } else { results["bodySelectionCreatesAnnotationWithoutSending"] = false }
        if let view = views.first(where: { $0.text.hasPrefix("你可以选择") }),
           let menu = view.delegate?.textView?(view, editMenuForTextIn: NSRange(location: 0, length: 5), suggestedActions: []),
           let action = menu.children.compactMap({ $0 as? UIAction }).first(where: { $0.title == "在临时聊天中提问" }) {
            let button = UIButton(); button.addAction(action, for: .touchUpInside)
            let original = model.history
            model.history = original.setting("controls", original["controls"].setting("supportedOperations", .array([])))
            button.sendActions(for: .touchUpInside)
            try? await Task.sleep(for: .milliseconds(150))
            results["revokedMenuCannotCreate"] = ConversationVisualTransport.state.counts.0 == 0
            model.history = original
            model.selectedThread = try! Record(.object(["id": .string("other"), "title": .string("other")]))
            button.sendActions(for: .touchUpInside)
            try? await Task.sleep(for: .milliseconds(150))
            results["staleThreadMenuCannotCreate"] = ConversationVisualTransport.state.counts.0 == 0
            model.selectedThread = thread
            let parentDraft = model.draft
            try? await Task.sleep(for: .milliseconds(200))
            if let fresh = textViews(window).first(where: { $0.text.hasPrefix("你可以选择") }),
               let freshMenu = fresh.delegate?.textView?(fresh, editMenuForTextIn: NSRange(location: 0, length: 5), suggestedActions: []),
               let freshAction = freshMenu.children.compactMap({ $0 as? UIAction }).first(where: { $0.title == "在临时聊天中提问" }) {
                let freshButton = UIButton(); freshButton.addAction(freshAction, for: .touchUpInside); freshButton.sendActions(for: .touchUpInside)
            }
            for _ in 0..<30 {
                try? await Task.sleep(for: .milliseconds(100))
                if ConversationVisualTransport.state.counts.0 > 0, model.draftStore.texts[model.scope + "\nside:" + thread.id + ":" + ConversationVisualTransport.sideID] != nil { break }
            }
            results["selectionSeedsSideDraft"] = model.draftStore.texts[model.scope + "\nside:" + thread.id + ":" + ConversationVisualTransport.sideID] == (view.text as NSString).substring(with: NSRange(location: 0, length: 5))
            results["selectionDoesNotSend"] = ConversationVisualTransport.state.counts == (1, 0)
            results["parentDraftPreserved"] = model.draft == parentDraft
            for _ in 0..<20 {
                if model.sideThreadID == ConversationVisualTransport.sideID { break }
                try? await Task.sleep(for: .milliseconds(100))
            }
            model.sideHistory = .object([
                "thread": .object(["id": .string(ConversationVisualTransport.sideID)]),
                "parentId": .string(thread.id), "status": .object(["state": .string("idle")]),
                "access": .object(["canInteract": .bool(true), "nativeReady": .bool(true)]),
                "controls": .object(["supportedOperations": .array([.string("settings")]), "settings": .object([
                    "model": .string("gpt-5.5-with-a-long-fixture-model-name"), "effort": .string("high")])]),
                "timeline": .array([])])
            try? await Task.sleep(for: .milliseconds(500))
            let sideImage = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? sideImage.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("side-model-long.png"))
        } else { results["selectionMenu"] = false }
        results["passed"] = results.values.allSatisfy { $0 }
        var result: [String: Any] = results
        result["comparisonLines"] = comparisonLines
        result["compactDiagnostics"] = compactDiagnostics
        result["creates"] = ConversationVisualTransport.state.counts.0
        result["sends"] = ConversationVisualTransport.state.counts.1
        result["modelError"] = model.error ?? ""
        result["canWrite"] = model.canWrite
        result["thread"] = model.selectedThread?.id ?? ""
        result["textViews"] = textViews(window).map { $0.text ?? "" }
        result["draftKeys"] = Array(model.draftStore.texts.keys)


        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("conversationvisual-result.json"))
    }
}
