# Owned simulator fixture hooks for the production side-chat menu handler.
p = source / 'CarryOn/App/SideChatsView.swift'
s = p.read_text()
start = s.index('private struct SideChatConversation:')
head, tail = s[:start], s[start:]
tail = tail.replace('    @State private var selectionText:', '    @State private var fixtureMessageMenu: ((CarryOnMessageAction) -> Void)?\n    @State private var selectionText:', 1)
tail = tail.replace('        .sheet(isPresented: $showingModel)', '''        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.side.retainMenu"))) { note in
            if let id = note.object as? String, messages.contains(where: { $0.id == id }) {
                let scope = model.scope, epoch = model.epoch
                fixtureMessageMenu = { action in performMessageAction(action, messageID: id, scope: scope, epoch: epoch) }
                NotificationCenter.default.post(name: .init("fixture.side.menuReceipt"), object: ["retained": true])
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.side.applyMenu"))) { note in
            if let fixtureMessageMenu {
                fixtureMessageMenu(note.object as? String == "select" ? .selectText : .copy)
                NotificationCenter.default.post(name: .init("fixture.side.menuReceipt"), object: ["selection": selectionText ?? "", "invoked": true])
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.side.clearSelection"))) { _ in selectionText = nil }
        .sheet(isPresented: $showingModel)''', 1)
p.write_text(head + tail)
# Distinguish the mounted selection sheet from the underlying Markdown paragraph.
m=source/'CarryOn/App/MessageMarkdown.swift';u=m.read_text();a=u.index('private struct SourceTextView:');u=u[:a]+u[a:].replace('let view = UITextView()', 'let view = UITextView()\n        view.accessibilityIdentifier = "fixture-selection-text-view"',1);m.write_text(u)
p = source / 'CarryOn/App/CarryOnApp.swift'
s = p.read_text()
app_hook = '.environment(fixture.model).task { await fixture.capture() }'
if app_hook not in s:
    raise RuntimeError('Side menu fixture receipt receiver missing')
s = s.replace(app_hook, '.environment(fixture.model).onReceive(NotificationCenter.default.publisher(for: .init("fixture.side.menuReceipt"))) { fixture.sideMenuReceipt = $0.object as? [String: Any] ?? [:] }.task { await fixture.capture() }', 1)
s = s.replace('    let model = AppModel()', '    @ObservationIgnored var sideMenuReceipt: [String: Any] = [:]\n    let model = AppModel()', 1)
anchor = '            let sideImage = UIGraphicsImageRenderer'
checks = '''            let sideBase = model.sideHistory
            func sideBody(_ text: String) {
                model.sideHistory = sideBase.setting("timeline", .array([.object(["id": .string("side-menu-answer"), "type": .string("agentMessage"), "text": .string(text)])]))
            }
            sideBody("旧菜单正文")
            try? await Task.sleep(for: .milliseconds(600))
            NotificationCenter.default.post(name: .init("fixture.side.retainMenu"), object: "side-menu-answer")
            results["sideMenuRetainsMountedMessage"] = sideMenuReceipt["retained"] as? Bool == true
            sideBody("**最新**菜单正文")
            try? await Task.sleep(for: .milliseconds(600))
            let savedClipboard = UIPasteboard.general.items
            NotificationCenter.default.post(name: .init("fixture.side.applyMenu"), object: "copy")
            results["sideRetainedMenuCopiesLatestRawText"] = UIPasteboard.general.string == "**最新**菜单正文" && sideMenuReceipt["invoked"] as? Bool == true
            NotificationCenter.default.post(name: .init("fixture.side.applyMenu"), object: "select")
            try? await Task.sleep(for: .milliseconds(700))
            results["sideSelectionUsesLatestPlainText"] = (sideMenuReceipt["selection"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) == "最新菜单正文"
            results["sideSelectionSheetActuallyMounted"] = textViews(window).contains { $0.accessibilityIdentifier == "fixture-selection-text-view" && !$0.isEditable && $0.text.trimmingCharacters(in: .whitespacesAndNewlines) == "最新菜单正文" && $0.window != nil }
            results["sideSelectDoesNotCopy"] = UIPasteboard.general.string == "**最新**菜单正文"
            model.devices = [try! Record(originalDevices[0].value.setting("permissions", .array([])))]
            try? await Task.sleep(for: .milliseconds(650))
            results["sideOpenSelectionDismissesAfterViewRevocation"] = !textViews(window).contains { $0.accessibilityIdentifier == "fixture-selection-text-view" && $0.window != nil }
            UIPasteboard.general.string = "未授权菜单不应修改"
            sideMenuReceipt = [:]
            NotificationCenter.default.post(name: .init("fixture.side.applyMenu"), object: "copy")
            results["sideRevokedMenuDoesNotCopy"] = UIPasteboard.general.string == "未授权菜单不应修改" && sideMenuReceipt["invoked"] as? Bool == true
            NotificationCenter.default.post(name: .init("fixture.side.applyMenu"), object: "select")
            results["sideRevokedMenuDoesNotSelect"] = sideMenuReceipt["selection"] as? String == ""
            model.devices = originalDevices
            model.sideThreadID = "different-side"
            sideMenuReceipt = [:]
            NotificationCenter.default.post(name: .init("fixture.side.applyMenu"), object: "copy")
            results["sideSwitchedMenuDoesNotCopy"] = UIPasteboard.general.string == "未授权菜单不应修改" && sideMenuReceipt["invoked"] as? Bool == true
            model.sideThreadID = ConversationVisualTransport.sideID
            UIPasteboard.general.items = savedClipboard
            model.sideHistory = sideBase
            try? await Task.sleep(for: .milliseconds(400))
'''
if anchor not in s:
    raise RuntimeError('Side menu regression observation point missing')
s = s.replace(anchor, checks + anchor, 1)
p.write_text(s)
