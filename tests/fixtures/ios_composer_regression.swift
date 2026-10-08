import SwiftUI
import CarryOnCore
import ExyteChat

@main struct ComposerRegressionApp: App {
    @State private var fixture = ComposerFixture()
    var body: some Scene {
        WindowGroup {
            VStack {
                Spacer()
                CarryOnChatComposer(text: $fixture.text, skills: $fixture.skills, selection: $fixture.selection,
                                    hasImages: !fixture.skills.isEmpty, send: {}) {
                    Image(systemName: "plus").frame(width: 44, height: 44)
                    Text("GPT-5.5 High").font(.subheadline)
                    Spacer()
                }.environment(\.chatTheme, ChatTheme(colors: .init(mainBG: Design.canvas, mainTint: Design.ink, inputBG: Design.input, inputText: Design.ink, sendButtonBackground: Design.composerAccent)))
            }.background(Design.canvas).task { await fixture.run() }
        }
    }
}
@MainActor @Observable final class ComposerFixture {
    var text = "使用 \u{fffc} 检查交互，然后说明结果。"
    var skills = [ComposerReference(name: "Review", path: "/fixture/SKILL.md", offset: 3)]
    var selection = 4
    private var started = false
    func run() async {
        guard !started else { return }; started = true
        try? await Task.sleep(for: .seconds(2))
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) else { return }
        func editor(_ view: UIView) -> UITextView? {
            if let value = view as? UITextView { return value }
            return view.subviews.lazy.compactMap(editor).first
        }
        guard let view = editor(window) else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("composer.png"))
        var results: [String: Bool] = [:]
        results["inlineAttachment"] = view.attributedText.attribute(.attachment, at: 3, effectiveRange: nil) != nil
        results["accessibleName"] = view.accessibilityValue?.contains("Review") == true
        view.becomeFirstResponder(); view.selectedRange = NSRange(location: 3, length: 1)
        view.copy(nil)
        results["copyReadableName"] = UIPasteboard.general.string == "Review"
        view.cut(nil)
        results["atomicDelete"] = skills.isEmpty && !text.contains(ComposerDocument.marker)
        try? await Task.sleep(for: .milliseconds(100))
        view.selectedRange = NSRange(location: 0, length: 0)
        UIPasteboard.general.string = "中文 👋\u{fffc} "
        view.paste(nil)
        results["plainPasteCannotForgeSkill"] = skills.isEmpty && text.hasPrefix("中文 👋 ") && !text.contains(ComposerDocument.marker)
        var document = ComposerDocument(text: text, skills: skills)
        document.insert(.init(name: "Review", path: "/fixture/SKILL.md"), at: 2)
        text = document.text; skills = document.skills; selection = 3
        try? await Task.sleep(for: .milliseconds(150))
        results["insertAtCursor"] = view.attributedText.attribute(.attachment, at: 2, effectiveRange: nil) != nil && skills[0].offset == 2
        let first = ComposerDocument(text: text, skills: skills)
        text = "另一个会话的草稿"; skills = []; selection = 0
        try? await Task.sleep(for: .milliseconds(100))
        results["scopeIsolation"] = view.text == "另一个会话的草稿"
        text = first.text; skills = first.skills
        try? await Task.sleep(for: .milliseconds(100))
        results["restoreIdentityAndPosition"] = view.attributedText.attribute(.attachment, at: 2, effectiveRange: nil) != nil && skills[0].value["path"].text == "/fixture/SKILL.md"
        view.selectedRange = NSRange(location: 0, length: 2)
        let range = view.selectedRange
        view.font = .systemFont(ofSize: 23)
        selection = 1
        try? await Task.sleep(for: .milliseconds(150))
        results["fontRefreshPreservesSelection"] = view.selectedRange == range && abs((view.font?.pointSize ?? 0) - ComposerTypography.font.pointSize) < 0.1
        text = Array(repeating: "Long editable paragraph with 中文 and emoji 👋.", count: 12).joined(separator: "\n")
        skills = []; selection = 0
        try? await Task.sleep(for: .milliseconds(200))
        results["sixLineCapScrollsInternally"] = view.isScrollEnabled && view.contentSize.height > view.bounds.height
        var fragments: [CGRect] = []
        view.layoutManager.ensureLayout(for: view.textContainer)
        view.layoutManager.enumerateLineFragments(forGlyphRange: view.layoutManager.glyphRange(for: view.textContainer)) { rect, _, _, _, _ in fragments.append(rect) }
        results["sixWholeLinesBeforeClippingSeventh"] = fragments.count >= 7 && abs(fragments[5].maxY - view.bounds.height) <= 1 && fragments[6].maxY > view.bounds.height + 1
        let composingText = view.text ?? ""
        view.setMarkedText("拼音", selectedRange: NSRange(location: 2, length: 0))
        let marked = view.markedTextRange != nil
        selection = 1
        try? await Task.sleep(for: .milliseconds(150))
        results["markedCompositionNotRebuilt"] = marked && view.markedTextRange != nil && view.text.contains("拼音")
        view.unmarkText()
        text = composingText
        results["passed"] = results.values.allSatisfy { $0 }
        try? JSONSerialization.data(withJSONObject: results).write(to: URL.documentsDirectory.appendingPathComponent("composer-result.json"))
    }
}
