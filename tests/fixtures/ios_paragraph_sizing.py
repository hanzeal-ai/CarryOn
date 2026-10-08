p=source/'CarryOn/App/MessageMarkdown.swift';s=p.read_text();s+='''
@MainActor @Observable private final class FixtureParagraphSizingState {
    var text = String(repeating: "Text changes should preserve accurate measurement. ", count: 5)
    var width: CGFloat = 250
    var font: CGFloat = 17
    var dark = false
    var side = true
}
private struct FixtureParagraphSizingRoot: View {
    let state: FixtureParagraphSizingState
    var body: some View {
        SelectableMarkdownParagraph(markdown: state.text, fontSize: state.font,
            askInSide: state.side ? { _ in } : nil, editMessage: nil)
            .frame(width: state.width).fixedSize(horizontal: false, vertical: true)
            .environment(\\.colorScheme, state.dark ? .dark : .light)
    }
}
@MainActor func fixtureParagraphSizingProbe() async -> [String: Bool] {
    guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first else { return ["sizingScene": false] }
    let state = FixtureParagraphSizingState()
    let host = UIHostingController(rootView: FixtureParagraphSizingRoot(state: state))
    let window = UIWindow(windowScene: scene)
    window.frame = CGRect(x: 0, y: 0, width: 340, height: 700)
    window.windowLevel = .normal + 1
    window.rootViewController = host; window.isHidden = false
    defer { window.isHidden = true }
    var initial: ObjectIdentifier?
    var results: [String: Bool] = [:]
    func textView(_ view: UIView) -> UITextView? {
        if let text = view as? UITextView { return text }
        return view.subviews.lazy.compactMap { textView($0) }.first
    }
    for step in ["initial", "grow", "shrink", "narrow", "wide", "restoreWidth", "largeFont", "smallFont", "dark", "revokeSide", "restoreSide"] {
        switch step {
        case "grow": state.text += String(repeating: "Appended content adds lines. ", count: 7)
        case "shrink": state.text = "Short text."
        case "narrow": state.text = String(repeating: "Width changes should recompute wrapped lines. ", count: 5); state.width = 145
        case "wide": state.width = 285
        case "restoreWidth": state.width = 250
        case "largeFont": state.font = 27
        case "smallFont": state.font = 14
        case "dark": state.dark = true
        case "revokeSide": state.side = false
        case "restoreSide": state.side = true
        default: break
        }
        try? await Task.sleep(for: .milliseconds(300))
        window.layoutIfNeeded()
        guard let view = textView(host.view), let coordinator = view.delegate as? SelectableMarkdownParagraph.Coordinator,
              let measurement = coordinator.measurements.first(where: { $0.width == state.width }), view.attributedText.length > 0 else { results["sizing-" + step] = false; continue }
        let id = ObjectIdentifier(view)
        if initial == nil { initial = id }
        let font = view.attributedText.attribute(.font, at: 0, effectiveRange: nil) as? UIFont
        let height = ceil(view.sizeThatFits(CGSize(width: measurement.width, height: .greatestFiniteMagnitude)).height)
        let menu = view.delegate?.textView?(view, editMenuForTextIn: NSRange(location: 0, length: 1), suggestedActions: [])
        let side = menu?.children.contains { ($0 as? UIAction)?.title == "在临时聊天中提问" } == true
        func glyphBoxes() -> [CGRect] {
            view.layoutManager.ensureLayout(for: view.textContainer)
            var boxes: [CGRect] = []
            view.layoutManager.enumerateLineFragments(forGlyphRange: NSRange(location: 0, length: view.layoutManager.numberOfGlyphs)) { _, used, _, _, _ in boxes.append(used) }
            return boxes
        }
        let before = glyphBoxes()
        let unbounded = coordinator.measuredHeight(for: .infinity, in: view)
        let bounded = coordinator.measuredHeight(for: state.width, in: view)
        let after = glyphBoxes()
        let stableGlyphs = !before.isEmpty && before.count == after.count && zip(before, after).allSatisfy { first, second in
            abs(first.minX - second.minX) < 0.5 && abs(first.minY - second.minY) < 0.5 && abs(first.width - second.width) < 0.5 && abs(first.height - second.height) < 0.5
        }
        results["sizing-" + step] = unbounded.isFinite && bounded.isFinite && abs(bounded - height) < 1 && stableGlyphs && initial == id && view.text == state.text.trimmingCharacters(in: .newlines)
            && abs(measurement.width - state.width) < 0.5 && abs(measurement.height - height) < 1
            && abs(view.bounds.height - height) < 1 && font?.pointSize == state.font && side == state.side
    }
    return results
}
''';p.write_text(s)
p=source/'CarryOn/App/CarryOnApp.swift';s=p.read_text()
s=s.replace('extraAssertions.count == 13','extraAssertions.count == 24',1)
s=s.replace('        var readingAnchorPreserved = false','        if boundaryOnly { extraAssertions.merge(await fixtureParagraphSizingProbe(), uniquingKeysWith: { _, new in new }) }\n        var readingAnchorPreserved = false',1)
p.write_text(s)
