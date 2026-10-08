# Owned fixture instrumentation only; the product implementation is untouched.
p=source/'CarryOn/App/ConversationView.swift'
s=p.read_text()
s=s.replace('    @State private var commandPanel:', '    @State private var fixtureMenuMessage: (String, String, UUID)?\n    @State private var commandPanel:',1)
hooks='''
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.menuRetain"))) { note in
            if let message = chatMessages.first(where: { $0.id == note.object as? String }) { fixtureMenuMessage = (message.id, model.scope, model.epoch) }
        }
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.menuApply"))) { note in
            if let message = fixtureMenuMessage {
                let action = note.object as? String ?? "copy"
                performMessageAction(action == "edit" ? .edit : action == "select" ? .selectText : .copy, messageID: message.0, scope: message.1, epoch: message.2)
                NotificationCenter.default.post(name: .init("fixture.menuReceipt"), object: ["selectedText": selectionText ?? "", "editingDraft": model.editingDraft, "editingItem": model.editingMessage["text"].text])
                selectionText = nil
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.rowQuery"))) { _ in
            let values = Dictionary(chatMessages.compactMap { message -> (String, String)? in
                guard let row = message.presentation else { return nil }
                return (message.id, row.item["text"].text)
            }, uniquingKeysWith: { first, _ in first })
            NotificationCenter.default.post(name: .init("fixture.rowReceipt"), object: values)
        }
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.pin"))) { _ in navigate(to: "a3") }
'''
s=s.replace('        .onChange(of: visibleCount)', '        .background { Color.clear' + hooks + '\n        }\n        .onChange(of: visibleCount)',1)
s=s.replace('else { prepared = await MessageMarkdownParser.shared.prepare(item) }','''else {
                if item["text"].text.hasPrefix("fixture-await-") {
                    NotificationCenter.default.post(name: .init("fixture.prepareWait"), object: item["text"].text)
                    try? await Task.sleep(for: .milliseconds(200))
                }
                prepared = await MessageMarkdownParser.shared.prepare(item)
            }''')
s=s.replace('if row.item != item { row.item = item }','''if row.item != item {
                        row.item = item
                        NotificationCenter.default.post(name: .init("fixture.rowPublished"), object: item["text"].text)
                    }''')
p.write_text(s)
p=source/'CarryOn/App/CarryOnApp.swift';s=p.read_text()
s=s.replace('                .task { await fixture.run() }','''                .onReceive(NotificationCenter.default.publisher(for: .init("fixture.menuReceipt"))) { fixture.menuReceipt = $0.object as? [String: String] ?? [:] }
                .onReceive(NotificationCenter.default.publisher(for: .init("fixture.rowReceipt"))) { fixture.rowReceipt = $0.object as? [String: String] ?? [:] }
                .onReceive(NotificationCenter.default.publisher(for: .init("fixture.prepareWait"))) { fixture.breakContext($0.object as? String ?? "") }
                .onReceive(NotificationCenter.default.publisher(for: .init("fixture.rowPublished"))) { if let value = $0.object as? String { fixture.published.append(value) } }
                .task { await fixture.run() }''',1)
s=s.replace('    var rows: [JSONValue] = []','''    var extraAssertions: [String: Bool] = [:]
    var menuReceipt: [String: String] = [:]
    var rowReceipt: [String: String] = [:]
    var published: [String] = []
    var brokeContext = false
    var rows: [JSONValue] = []''',1)
s=s.replace('        var readingAnchorPreserved = false','        if boundaryOnly { await verifyRowActions() }\n        var readingAnchorPreserved = false',1)
s=s.replace('let result: [String: Any] = ["readingAnchors":', 'let result: [String: Any] = ["extraAssertions": extraAssertions, "readingAnchors":',1)
s=s.replace('"passed": glyphCases.allSatisfy', '"passed": (!boundaryOnly || (extraAssertions.count == 13 && extraAssertions.values.allSatisfy { $0 })) && glyphCases.allSatisfy',1)
a=s.index('    func recordTiming(')
s=s[:a]+'''
    func breakContext(_ text: String) {
        brokeContext = true
        if text == "fixture-await-scope" { model.addressText = "https://scope-fixture.invalid/" }
        else { model.selectedThread = nil }
    }
    func menu(_ action: String) {
        NotificationCenter.default.post(name: .init("fixture.menuApply"), object: action)
    }
    func updateMenuUser(_ text: String) {
        if let index = rows.firstIndex(where: { $0["id"].text == "u3" }) {
            rows[index] = entry("u3", "userMessage", text).setting("turnId", .string("menu-turn"))
        }
        sync()
        model.history = model.history.setting("controls", .object(["supportedOperations": .array([.string("side-create"), .string("edit")]), "lastTurnId": .string("menu-turn"), "lastUserText": .string(text)]))
        model.historyRevision += 1
    }
    func sideTargetVisible() -> Bool {
        keyWindow.flatMap { table(in: $0) }?.visibleCells.contains { messageID($0) == "a3" } == true
    }
    func nativeSideMenuAvailable() -> Bool {
        guard let window = keyWindow, let table = table(in: window),
              let cell = table.visibleCells.first(where: { messageID($0) == "a3" }) else { return false }
        return textViews(in: cell).filter { !$0.isEditable && !$0.text.isEmpty }.contains { view in
            let menu = view.delegate?.textView?(view, editMenuForTextIn: NSRange(location: 0, length: 1), suggestedActions: [])
            return menu?.children.contains { ($0 as? UIAction)?.title == "在临时聊天中提问" } == true
        }
    }
    func verifyRowActions() async {
        let originalRows = rows, originalDevices = model.devices, originalAddress = model.addressText
        guard let index = rows.firstIndex(where: { $0["id"].text == "a3" }) else { extraAssertions["setup"] = false; return }
        rows[index] = entry("a3", "agentMessage", "菜单初始正文"); sync()
        try? await Task.sleep(for: .milliseconds(350))
        NotificationCenter.default.post(name: .init("fixture.latest"), object: nil)
        try? await Task.sleep(for: .milliseconds(600))
        extraAssertions["sideMenuInitiallyAvailable"] = nativeSideMenuAvailable()
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "send", "edit"].map(JSONValue.string))]))]
        try? await Task.sleep(for: .milliseconds(500))
        extraAssertions["sideMenuRemovedAfterPermissionRevocation"] = sideTargetVisible() && !nativeSideMenuAvailable()
        model.devices = originalDevices
        try? await Task.sleep(for: .milliseconds(500))
        extraAssertions["sideMenuRestoredAfterPermissionRestore"] = nativeSideMenuAvailable()
        model.history = model.history.setting("controls", .object(["supportedOperations": .array([])])); model.historyRevision += 1
        try? await Task.sleep(for: .milliseconds(500))
        extraAssertions["sideMenuRemovedAfterCapabilityRevocation"] = sideTargetVisible() && !nativeSideMenuAvailable()
        sync()
        try? await Task.sleep(for: .milliseconds(500))
        extraAssertions["sideMenuRestoredAfterCapabilityRestore"] = nativeSideMenuAvailable()
        NotificationCenter.default.post(name: .init("fixture.menuRetain"), object: "a3")
        rows[index] = entry("a3", "agentMessage", "菜单最新正文"); sync()
        try? await Task.sleep(for: .milliseconds(350))
        let clipboard = UIPasteboard.general.items
        menu("copy"); extraAssertions["retainedMenuCopiesLatest"] = UIPasteboard.general.string == "菜单最新正文"
        UIPasteboard.general.items = clipboard
        menu("select"); extraAssertions["retainedMenuSelectsLatest"] = menuReceipt["selectedText"] == "菜单最新正文"
        updateMenuUser("编辑初始正文")
        try? await Task.sleep(for: .milliseconds(350))
        NotificationCenter.default.post(name: .init("fixture.menuRetain"), object: "u3")
        updateMenuUser("编辑最新正文")
        try? await Task.sleep(for: .milliseconds(350))
        menu("edit")
        extraAssertions["retainedMenuEditsLatest"] = menuReceipt["editingDraft"] == "编辑最新正文" && menuReceipt["editingItem"] == "编辑最新正文"
        model.cancelEditing()
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "send", "create"].map(JSONValue.string))]))]
        menu("edit"); extraAssertions["revokedOldMenuCannotEdit"] = model.editingMessage == .null
        model.devices = originalDevices
        rows = originalRows; sync()
        try? await Task.sleep(for: .milliseconds(350))
        NotificationCenter.default.post(name: .init("fixture.pin"), object: nil)
        try? await Task.sleep(for: .milliseconds(900))
        let before = readingAnchors.count
        rows[index] = entry("a3", "agentMessage", rows[index]["text"].text + String(repeating: "搜索固定后增长。", count: 30)); sync()
        try? await Task.sleep(for: .milliseconds(900))
        extraAssertions["pinnedGrowthDoesNotRestoreReading"] = readingAnchors.count == before
        extraAssertions["pinnedTargetRemainsVisible"] = keyWindow.flatMap { table(in: $0) }?.visibleCells.contains { messageID($0) == "a3" } == true
        NotificationCenter.default.post(name: .init("fixture.latest"), object: nil)
        try? await Task.sleep(for: .milliseconds(350))
        for context in ["thread", "scope"] {
            let text = "fixture-await-" + context
            brokeContext = false; published = []
            rows[index] = entry("a3", "agentMessage", text); sync()
            try? await Task.sleep(for: .milliseconds(500))
            NotificationCenter.default.post(name: .init("fixture.rowQuery"), object: nil)
            extraAssertions[context + "WaitRejectsOldPublication"] = brokeContext && !published.contains(text) && rowReceipt["a3"] != text
            rows = originalRows; sync(); model.addressText = originalAddress; model.selectedThread = thread
            try? await Task.sleep(for: .milliseconds(400))
        }
    }
'''+s[a:]
p.write_text(s)
