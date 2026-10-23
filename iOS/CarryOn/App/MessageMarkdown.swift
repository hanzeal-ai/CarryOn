import SwiftUI
import MarkdownUI
import Highlightr
import CarryOnCore

struct MessageMarkdown: View {
    @Environment(AppModel.self) private var model
    @Environment(\.preparedMessageMarkdown) private var prepared
    @Environment(\.addMessageAnnotation) private var addAnnotation
    @Environment(\.askInSideChat) private var askInSide
    @Environment(\.editConversationMessage) private var editMessage
    let text: String
    @ScaledMetric(relativeTo: .body) private var bodySize = 17
    var artifacts: [JSONValue] = []
    var threadID: String = ""
    var resolveCreatedThreads = false
    @State private var threadTitles: [String: String] = [:]
    @State private var openingThread = false
    @State private var parsed: ParsedMessageMarkdown?
    @State private var refresh = ConversationRefreshQueue()
    @State private var generation = UUID()
    private var input: MessageMarkdownInput { .init(text: text, resolveThreads: resolveCreatedThreads, titles: threadTitles) }
    private var displayed: ParsedMessageMarkdown? {
        if parsed?.input == input { return parsed }
        if prepared?.input == input { return prepared }
        // Title lookup may lag, but never display content from a different message.
        return [parsed, prepared].compactMap { $0 }.first {
            $0.input.text == input.text && $0.input.resolveThreads == input.resolveThreads
        }
    }
    private var createdIDs: [String] { displayed?.threadIDs ?? [] }
    @State private var selectedArtifact: JSONValue?
    @State private var previewID = UUID()
    var body: some View {
        Markdown(displayed?.content ?? MarkdownContent {})
            .markdownImageProvider(AttachmentImageProvider())
            .markdownInlineImageProvider(AttachmentInlineImageProvider())
            .markdownTextStyle { FontSize(bodySize); ForegroundColor(Design.ink) }
            .markdownTextStyle(\.link) { ForegroundColor(Design.link) }
            .markdownBlockStyle(\.paragraph) { configuration in
                if (addAnnotation != nil || askInSide != nil || editMessage != nil), !configuration.content.renderMarkdown().contains("![") {
                    SelectableMarkdownParagraph(markdown: configuration.content.renderMarkdown(), fontSize: bodySize, addAnnotation: addAnnotation, askInSide: askInSide, editMessage: editMessage)
                        .markdownMargin(top: 0, bottom: 8)
                } else { configuration.label.relativeLineSpacing(.em(0.20)).markdownMargin(top: 0, bottom: 8) }
            }
            .markdownBlockStyle(\.codeBlock) { configuration in
                CodeBlockView(code: configuration.content, language: configuration.language)
                    .markdownMargin(top: 8, bottom: 8)
            }
            .textSelection(.enabled)
            .onAppear { refreshMarkdown() }
            .onChange(of: input) { _, _ in refreshMarkdown() }
            .onChange(of: prepared?.input) { _, _ in refreshMarkdown() }
            .onDisappear { generation = UUID() }
            .environment(\.openURL, OpenURLAction { url in
                if url.scheme == "carryon-artifact", let ref = artifacts.first(where: { url.absoluteString == "carryon-artifact:" + $0["id"].text }) {
                    guard ConversationPresentation.artifactCanPreview(ref) else { return .discarded }
                    selectedArtifact = ref; previewID = UUID(); return .handled
                }
                if url.scheme == "carryon-thread", let id = createdIDs.first(where: { url.absoluteString == "carryon-thread:" + $0 }) {
                    guard !openingThread else { return .handled }
                    openingThread = true
                    Task { await model.openLinkedThread(id, from: threadID); openingThread = false }
                    return .handled
                }
                return ["https", "http", "mailto"].contains(url.scheme?.lowercased() ?? "") ? .systemAction : .discarded
            })
            .task(id: model.scope + createdIDs.joined()) {
                let scope = model.scope
                for id in createdIDs {
                    do {
                        let result = try await model.page("/api/workspace/threads?threadId=" + ConsoleAddress.component(id), key: "threads")
                        guard !Task.isCancelled, model.scope == scope else { return }
                        if let record = result.records.first(where: { $0.id == id }) { threadTitles[id] = record.title }
                    } catch { if Task.isCancelled { return } }
                }
            }
            .background {
                if let selectedArtifact {
                    ArtifactView(ref: selectedArtifact, threadID: threadID, openOnLoad: true).id(previewID)
                }
            }
    }
    private func refreshMarkdown() {
        let request = input, version = generation
        guard displayed?.input != request else { return }
        refresh.request {
            guard generation == version else { return }
            let result = await MessageMarkdownParser.shared.render(request)
            if generation == version { parsed = result }
        }
    }
}

private struct EditConversationMessageKey: EnvironmentKey {
    static let defaultValue: (@MainActor @Sendable () -> Void)? = nil
}
extension EnvironmentValues {
    var editConversationMessage: (@MainActor @Sendable () -> Void)? {
        get { self[EditConversationMessageKey.self] }
        set { self[EditConversationMessageKey.self] = newValue }
    }
}

private struct AddMessageAnnotationKey: EnvironmentKey {
    static let defaultValue: (@MainActor @Sendable (String) -> Void)? = nil
}
extension EnvironmentValues {
    var addMessageAnnotation: (@MainActor @Sendable (String) -> Void)? {
        get { self[AddMessageAnnotationKey.self] }
        set { self[AddMessageAnnotationKey.self] = newValue }
    }
}

private struct AskInSideChatKey: EnvironmentKey {
    static let defaultValue: (@MainActor @Sendable (String) -> Void)? = nil
}
extension EnvironmentValues {
    var askInSideChat: (@MainActor @Sendable (String) -> Void)? {
        get { self[AskInSideChatKey.self] }
        set { self[AskInSideChatKey.self] = newValue }
    }
}

/// Public TextKit selection menus, embedded in MarkdownUI's paragraph layout.
private struct SelectableMarkdownParagraph: UIViewRepresentable {
    let markdown: String
    let fontSize: CGFloat
    let addAnnotation: (@MainActor @Sendable (String) -> Void)?
    let askInSide: (@MainActor @Sendable (String) -> Void)?
    let editMessage: (@MainActor @Sendable () -> Void)?
    @Environment(\.conversationSelectionChanged) private var selectionChanged
    @Environment(\.openURL) private var openURL
    @Environment(\.colorScheme) private var colorScheme
    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: SelectableMarkdownParagraph
        var renderedKey = ""
        var measurements: [(width: CGFloat, height: CGFloat)] = []
        func measuredHeight(for width: CGFloat, in view: UITextView) -> CGFloat {
            if let measurement = measurements.first(where: { $0.width == width }) { return measurement.height }
            let height = ceil(view.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude)).height)
            if measurements.count == 2 { measurements.removeFirst() }
            measurements.append((width, height))
            return height
        }
        var updatingSelection = false
        func textViewDidChangeSelection(_ textView: UITextView) {
            if !updatingSelection { parent.selectionChanged?(textView) }
        }
        func textViewDidEndEditing(_ textView: UITextView) {
            if !updatingSelection { parent.selectionChanged?(textView) }
        }
        init(_ parent: SelectableMarkdownParagraph) { self.parent = parent }
        func textView(_ textView: UITextView, editMenuForTextIn range: NSRange, suggestedActions: [UIMenuElement]) -> UIMenu? {
            guard range.length > 0, range.location >= 0, NSMaxRange(range) <= (textView.text as NSString).length else { return UIMenu(children: suggestedActions) }
            let selected = (textView.text as NSString).substring(with: range)
            var actions: [UIMenuElement] = []
            if parent.addAnnotation != nil { actions.append(UIAction(title: "添加到聊天", image: UIImage(systemName: "bubble.left")) { [weak self, weak textView] _ in
                self?.parent.addAnnotation?(selected)
                textView?.selectedRange = NSRange(location: 0, length: 0)
                textView?.resignFirstResponder()
            }) }
            if parent.askInSide != nil { actions.append(UIAction(title: "在临时聊天中提问", image: UIImage(systemName: "bubble.left.and.bubble.right")) { [weak self] _ in self?.parent.askInSide?(selected) }) }
            if parent.editMessage != nil { actions.append(UIAction(title: "编辑消息", image: UIImage(systemName: "pencil")) { [weak self] _ in self?.parent.editMessage?() }) }
            return UIMenu(children: actions + suggestedActions)
        }
        func textView(_ textView: UITextView, primaryActionFor textItem: UITextItem, defaultAction: UIAction) -> UIAction? {
            guard case let .link(url) = textItem.content else { return defaultAction }
            return UIAction { [weak self] _ in self?.parent.openURL(url) }
        }
    }
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.delegate = context.coordinator
        view.isEditable = false; view.isSelectable = true; view.isScrollEnabled = false
        view.backgroundColor = .clear; view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return view
    }
    func updateUIView(_ view: UITextView, context: Context) {
        context.coordinator.parent = self
        let key = markdown + String(describing: fontSize) + String(colorScheme == .dark)
        guard context.coordinator.renderedKey != key else { return }
        context.coordinator.renderedKey = key
        context.coordinator.measurements.removeAll(keepingCapacity: true)
        var value = (try? AttributedString(markdown: markdown.trimmingCharacters(in: .newlines), options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(markdown)
        for run in value.runs {
            let intent = run.inlinePresentationIntent ?? []
            var font = intent.contains(.code) ? UIFont.monospacedSystemFont(ofSize: fontSize, weight: .regular) : UIFont.systemFont(ofSize: fontSize)
            var traits = font.fontDescriptor.symbolicTraits
            if intent.contains(.stronglyEmphasized) { traits.insert(.traitBold) }
            if intent.contains(.emphasized) { traits.insert(.traitItalic) }
            if let descriptor = font.fontDescriptor.withSymbolicTraits(traits) { font = UIFont(descriptor: descriptor, size: fontSize) }
            if intent.contains(.strikethrough) { value[run.range].strikethroughStyle = .single }
            value[run.range].font = font
            value[run.range].foregroundColor = UIColor(Design.ink)
        }
        let oldText = view.text ?? "", selection = view.selectedRange
        let preserveSelection = view.isFirstResponder && selection.length > 0 && !oldText.isEmpty && String(value.characters).hasPrefix(oldText)
        context.coordinator.updatingSelection = true
        defer { context.coordinator.updatingSelection = false }
        view.linkTextAttributes = [.foregroundColor: UIColor(Design.link)]
        let attributed = NSMutableAttributedString(attributedString: NSAttributedString(value))
        let paragraph = NSMutableParagraphStyle(); paragraph.lineSpacing = fontSize * 0.20
        attributed.addAttribute(.paragraphStyle, value: paragraph, range: NSRange(location: 0, length: attributed.length))
        view.attributedText = attributed
        if preserveSelection, NSMaxRange(selection) <= (view.text as NSString).length { view.selectedRange = selection }
    }
    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        guard let width = proposal.width, width > 0 else { return nil }
        return CGSize(width: width, height: context.coordinator.measuredHeight(for: width, in: uiView))
    }
}

struct MessageMarkdownInput: Hashable, Sendable {
    let text: String
    let resolveThreads: Bool
    let titles: [String: String]
}

// MarkdownUI's parsed tree contains immutable value types but does not declare Sendable.
struct ParsedMessageMarkdown: @unchecked Sendable {
    let input: MessageMarkdownInput
    let content: MarkdownContent
    let threadIDs: [String]
}

private struct PreparedMarkdownKey: EnvironmentKey {
    static let defaultValue: ParsedMessageMarkdown? = nil
}
extension EnvironmentValues {
    var preparedMessageMarkdown: ParsedMessageMarkdown? {
        get { self[PreparedMarkdownKey.self] }
        set { self[PreparedMarkdownKey.self] = newValue }
    }
}

actor MessageMarkdownParser {
    static let shared = MessageMarkdownParser()
    private var cache: [MessageMarkdownInput: ParsedMessageMarkdown] = [:]
    private var order: [MessageMarkdownInput] = []
    private var bytes = 0
    func prepare(_ item: JSONValue) -> ParsedMessageMarkdown? {
        let kind = item["type"].text
        guard ["userMessage", "steeringUserMessage", "agentMessage"].contains(kind) else { return nil }
        let user = kind != "agentMessage"
        let text = user ? (item["displayText"].string ?? item["text"].text) : ConversationPresentation.attachmentDisplayText(item)
        return render(.init(text: text, resolveThreads: !user, titles: [:]))
    }
    func render(_ input: MessageMarkdownInput) -> ParsedMessageMarkdown {
        if let cached = cache[input] { return cached }
        let rendered = input.resolveThreads ? CreatedThreadReference.render(input.text, titles: input.titles) : input.text
        let result = ParsedMessageMarkdown(input: input, content: MarkdownContent(rendered),
            threadIDs: input.resolveThreads ? CreatedThreadReference.threadIDs(in: input.text) : [])
        let size = input.text.utf8.count
        if size <= 2 * 1024 * 1024 {
            cache[input] = result; order.append(input); bytes += size
            while order.count > 32 || bytes > 2 * 1024 * 1024 {
                let removed = order.removeFirst()
                cache.removeValue(forKey: removed); bytes -= removed.text.utf8.count
            }
        }
        return result
    }
}

struct CodeBlockView: View {
    @Environment(\.colorScheme) private var colorScheme
    let code: String
    let language: String?
    var allowsWrapping = false
    @State private var wraps = true
    @State private var highlighted: AttributedString?
    private var label: String { CodeDocument.normalizedLanguage(language) }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(label == "plaintext" ? "纯文本" : label).font(.caption.monospaced()).foregroundStyle(Design.secondary)
                Spacer()
                if allowsWrapping {
                    Button { wraps.toggle() } label: { Image(systemName: "arrow.turn.down.left") }
                        .foregroundStyle(Design.secondary).accessibilityLabel(wraps ? "关闭自动换行" : "开启自动换行").frame(minWidth: 44, minHeight: 44)
                }
                if !allowsWrapping { Button { UIPasteboard.general.string = code } label: { Image(systemName: "doc.on.doc") }
                    .accessibilityLabel("复制代码").frame(minWidth: 44, minHeight: 44)
                }
            }.padding(.horizontal, 12)
            if !allowsWrapping { Divider() }
            if allowsWrapping && wraps {
                Text(code)
                    .font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(12)
            } else { ScrollView(.horizontal) {
                Text(highlighted ?? AttributedString(code))
                    .font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                    .fixedSize(horizontal: true, vertical: true).padding(12)
            } }
        }.background(Design.background, in: RoundedRectangle(cornerRadius: Design.controlCorner))
            .clipShape(RoundedRectangle(cornerRadius: Design.controlCorner))
            .overlay(RoundedRectangle(cornerRadius: Design.controlCorner).stroke(allowsWrapping ? Design.border : .clear))
            .contextMenu { Button("复制代码") { UIPasteboard.general.string = code } }
            .task(id: label + "\n" + code + String(colorScheme == .dark)) {
                highlighted = nil
                let result = await CodeHighlight.shared.render(code, language: label, dark: colorScheme == .dark)
                if !Task.isCancelled { highlighted = result }
            }
    }
}

actor CodeHighlight {
    static let shared = CodeHighlight()
    private let engine: Highlightr? = {
        let engine = Highlightr()
        // This theme avoids descendant selectors the library flattens out of order.
        engine?.setTheme(to: "github-gist")
        return engine
    }()
    private var themeName = "github-gist"
    func render(_ code: String, language: String, dark: Bool) -> AttributedString? {
        let desired = dark ? "atom-one-dark" : "github-gist"
        if desired != themeName, engine?.setTheme(to: desired) == true { themeName = desired }
        guard code.utf8.count <= CodeDocument.highlightLimit, language != "plaintext",
              let result = engine?.highlight(code, as: language, fastRender: true) else { return nil }
        return try? AttributedString(result, including: \.uiKit)
    }
    func diff(_ patch: String, language: String, dark: Bool) -> [Int: AttributedString] {
        guard patch.utf8.count <= CodeDocument.highlightLimit else { return [:] }
        let previous = engine?.ignoreIllegals ?? false
        engine?.ignoreIllegals = true
        defer { engine?.ignoreIllegals = previous }
        var rows: [Int: AttributedString] = [:], group: [UnifiedDiff.Line] = []
        var groups = 0
        func flush() {
            guard !group.isEmpty else { return }
            defer { group.removeAll(keepingCapacity: true) }
            groups += 1
            guard groups <= 128 else { return }
            for removed in [true, false] {
                let side = group.filter { removed ? $0.kind != .added : $0.kind != .removed }
                guard !side.isEmpty else { continue }
                let source = side.map { String($0.text.dropFirst()) }.joined(separator: "\n")
                guard var colored = render(source, language: language, dark: dark), String(colored.characters) == source else { continue }
                // Typography and diff signs remain owned by the view; only source receives token colors.
                colored.uiKit.font = nil; colored.uiKit.paragraphStyle = nil; colored.uiKit.backgroundColor = nil
                var tokens: [AttributedString] = [], start = colored.startIndex
                for position in colored.characters.indices where colored.characters[position] == "\n" {
                    tokens.append(AttributedString(colored[start..<position])); start = colored.characters.index(after: position)
                }
                tokens.append(AttributedString(colored[start..<colored.endIndex]))
                guard tokens.count == side.count else { continue }
                for (index, line) in side.enumerated() where (line.kind == .removed) == removed {
                    let value = AttributedString(String(line.text.prefix(1))) + tokens[index]
                    if String(value.characters) == line.text { rows[line.id] = value }
                }
            }
        }
        for line in UnifiedDiff.lines(patch) {
            if line.kind == .header {
                if !line.text.hasPrefix("\\ No newline") { flush() }
            } else { group.append(line) }
        }
        flush()
        return rows
    }
}

struct CodeFilePreview: View {
    @Environment(\.colorScheme) private var colorScheme
    let document: CodeDocument
    let fileURL: URL?
    @Environment(\.dismiss) private var dismiss
    @State private var source = false
    @State private var highlighted: AttributedString?
    var body: some View {
        NavigationStack {
            Group {
                if document.isMarkdown && !source && document.text.utf8.count <= CodeDocument.highlightLimit {
                    ScrollView { MessageMarkdown(text: document.text).padding(16).frame(maxWidth: .infinity, alignment: .leading) }
                } else {
                    SourceTextView(text: highlighted ?? AttributedString(document.text))
                }
            }
            .navigationTitle(document.name).navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .top) {
                HStack {
                    Text(document.language).font(.caption.monospaced())
                    if document.text.utf8.count > CodeDocument.highlightLimit { Text("大文件以纯文本展示").font(.caption) }
                    Spacer()
                    if document.isMarkdown && document.text.utf8.count <= CodeDocument.highlightLimit {
                        Toggle("源码", isOn: $source).toggleStyle(.button).font(.caption)
                    }
                }.foregroundStyle(Design.secondary).padding(.horizontal, 16).padding(.vertical, 6)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if let fileURL {
                        ShareLink(item: fileURL) { Label("分享文件", systemImage: "square.and.arrow.up") }
                    }
                }
                ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
            }
            .task(id: document.id + String(colorScheme == .dark)) {
                highlighted = nil
                let result = await CodeHighlight.shared.render(document.text, language: document.language, dark: colorScheme == .dark)
                if !Task.isCancelled { highlighted = result }
            }
        }
    }
}

struct MessageTextSelectionView: View {
    let text: String
    var askInSide: ((String) -> Void)? = nil
    var addAnnotation: ((String) -> Void)? = nil
    @State private var selectedText = ""
    @Environment(\.dismiss) private var dismiss

    static func plainText(_ text: String, resolveCreatedThreads: Bool) -> String {
        let rendered = resolveCreatedThreads ? CreatedThreadReference.render(text, titles: [:]) : text
        return MarkdownContent(rendered).renderPlainText()
    }

    var body: some View {
        NavigationStack {
            SourceTextView(text: AttributedString(text), font: .preferredFont(forTextStyle: .body), selection: $selectedText, askInSide: askInSide, addAnnotation: addAnnotation.map { action in { text in action(text); dismiss() } })
                .navigationTitle("选择文字").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
                    if let askInSide {
                        ToolbarItem(placement: .bottomBar) {
                            Button("在临时聊天中提问") { askInSide(selectedText); dismiss() }.disabled(selectedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }
                }
        }
    }
}

/// TextKit handles long files without creating a SwiftUI view for every line.
private struct SourceTextView: UIViewRepresentable {
    let text: AttributedString
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    var font: UIFont? = nil
    var selection: Binding<String>? = nil
    var askInSide: ((String) -> Void)? = nil
    var addAnnotation: ((String) -> Void)? = nil
    final class Coordinator: NSObject, UITextViewDelegate {
        var selection: Binding<String>?
        var askInSide: ((String) -> Void)?
        var addAnnotation: ((String) -> Void)?
        init(selection: Binding<String>?, askInSide: ((String) -> Void)?) { self.selection = selection; self.askInSide = askInSide }
        func textView(_ textView: UITextView, editMenuForTextIn range: NSRange, suggestedActions: [UIMenuElement]) -> UIMenu? {
            guard range.location >= 0, range.length > 0, NSMaxRange(range) <= (textView.text as NSString).length else { return UIMenu(children: suggestedActions) }
            let selected = (textView.text as NSString).substring(with: range)
            var actions: [UIMenuElement] = []
            if let addAnnotation { actions.append(UIAction(title: "添加到聊天", image: UIImage(systemName: "bubble.left")) { _ in addAnnotation(selected) }) }
            if let askInSide { actions.append(UIAction(title: "在临时聊天中提问", image: UIImage(systemName: "bubble.left.and.bubble.right")) { _ in askInSide(selected) }) }
            return UIMenu(children: actions + suggestedActions)
        }
        func textViewDidChangeSelection(_ textView: UITextView) {
            guard let range = textView.selectedTextRange else { selection?.wrappedValue = ""; return }
            selection?.wrappedValue = textView.text(in: range) ?? ""
        }
    }
    func makeCoordinator() -> Coordinator { Coordinator(selection: selection, askInSide: askInSide) }
    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.delegate = context.coordinator
        view.textColor = .label
        view.isEditable = false
        view.isSelectable = true
        view.backgroundColor = .systemBackground
        view.textContainerInset = UIEdgeInsets(top: 12, left: 12, bottom: 20, right: 12)
        view.alwaysBounceVertical = true
        return view
    }
    func updateUIView(_ view: UITextView, context: Context) {
        context.coordinator.selection = selection
        context.coordinator.askInSide = askInSide
        context.coordinator.addAnnotation = addAnnotation
        let result = NSMutableAttributedString(text)
        let fullRange = NSRange(location: 0, length: result.length)
        let scaledFont = font ?? UIFontMetrics(forTextStyle: .footnote).scaledFont(for: .monospacedSystemFont(ofSize: 13, weight: .regular))
        result.addAttribute(.font, value: scaledFont, range: fullRange)
        result.enumerateAttribute(.foregroundColor, in: fullRange) { color, range, _ in
            if color == nil { result.addAttribute(.foregroundColor, value: UIColor.label, range: range) }
        }
        if !view.attributedText.isEqual(to: result) { view.attributedText = result }
    }
}

// Images referenced by messages are loaded through the existing authenticated attachment flow.
private struct AttachmentImageProvider: MarkdownUI.ImageProvider {
    func makeImage(url: URL?) -> some View { Image(systemName: "photo").accessibilityLabel("图片") }
}
private struct AttachmentInlineImageProvider: InlineImageProvider {
    func image(with url: URL, label: String) async throws -> Image { Image(systemName: "photo") }
}
