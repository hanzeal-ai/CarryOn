import SwiftUI
import MarkdownUI
import Highlightr
import CarryOnCore

struct MessageMarkdown: View {
    @Environment(AppModel.self) private var model
    let text: String
    var artifacts: [JSONValue] = []
    var threadID: String = ""
    var resolveCreatedThreads = false
    @State private var threadTitles: [String: String] = [:]
    @State private var openingThread = false
    private var createdIDs: [String] { resolveCreatedThreads ? CreatedThreadReference.threadIDs(in: text) : [] }
    @State private var selectedArtifact: JSONValue?
    @State private var previewID = UUID()
    var body: some View {
        Markdown(resolveCreatedThreads ? CreatedThreadReference.render(text, titles: threadTitles) : text)
            .markdownImageProvider(AttachmentImageProvider())
            .markdownInlineImageProvider(AttachmentInlineImageProvider())
            .markdownTextStyle { FontSize(17); ForegroundColor(Design.ink) }
            .markdownTextStyle(\.link) { ForegroundColor(Design.link) }
            .markdownBlockStyle(\.codeBlock) { configuration in
                CodeBlockView(code: configuration.content, language: configuration.language)
                    .markdownMargin(top: 8, bottom: 8)
            }
            .textSelection(.enabled)
            .environment(\.openURL, OpenURLAction { url in
                if url.scheme == "carryon-artifact", let ref = artifacts.first(where: { url.absoluteString == "carryon-artifact:" + $0["id"].text }) {
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
}

struct CodeBlockView: View {
    @Environment(\.colorScheme) private var colorScheme
    let code: String
    let language: String?
    @State private var highlighted: AttributedString?
    private var label: String { CodeDocument.normalizedLanguage(language) }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(label).font(.caption.monospaced()).foregroundStyle(Design.secondary)
                Spacer()
                Button { UIPasteboard.general.string = code } label: { Image(systemName: "doc.on.doc") }
                    .accessibilityLabel("复制代码").frame(minWidth: 44, minHeight: 36)
            }.padding(.horizontal, 12)
            Divider()
            ScrollView(.horizontal) {
                Text(highlighted ?? AttributedString(code))
                    .font(.system(size: 13, design: .monospaced)).textSelection(.enabled)
                    .fixedSize(horizontal: true, vertical: true).padding(12)
            }
        }.background(Design.background, in: RoundedRectangle(cornerRadius: Design.controlCorner))
            .clipShape(RoundedRectangle(cornerRadius: Design.controlCorner))
            .task(id: label + "\n" + code + String(colorScheme == .dark)) {
                highlighted = nil
                let result = await CodeHighlight.shared.render(code, language: label, dark: colorScheme == .dark)
                if !Task.isCancelled { highlighted = result }
            }
    }
}

private actor CodeHighlight {
    static let shared = CodeHighlight()
    private let engine: Highlightr? = {
        let engine = Highlightr()
        engine?.setTheme(to: "github")
        return engine
    }()
    func render(_ code: String, language: String, dark: Bool) -> AttributedString? {
        engine?.setTheme(to: dark ? "atom-one-dark" : "github")
        guard code.utf8.count <= CodeDocument.highlightLimit, language != "plaintext",
              let result = engine?.highlight(code, as: language, fastRender: true) else { return nil }
        return try? AttributedString(result, including: \.uiKit)
    }
}

struct CodeFilePreview: View {
    @Environment(\.colorScheme) private var colorScheme
    let document: CodeDocument
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
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
            .task(id: document.id + String(colorScheme == .dark)) {
                let result = await CodeHighlight.shared.render(document.text, language: document.language, dark: colorScheme == .dark)
                if !Task.isCancelled { highlighted = result }
            }
        }
    }
}

struct MessageTextSelectionView: View {
    let text: String
    @Environment(\.dismiss) private var dismiss

    static func plainText(_ text: String, resolveCreatedThreads: Bool) -> String {
        let rendered = resolveCreatedThreads ? CreatedThreadReference.render(text, titles: [:]) : text
        return MarkdownContent(rendered).renderPlainText()
    }

    var body: some View {
        NavigationStack {
            SourceTextView(text: AttributedString(text), font: .preferredFont(forTextStyle: .body))
                .navigationTitle("选择文字").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
                }
        }
    }
}

/// TextKit handles long files without creating a SwiftUI view for every line.
private struct SourceTextView: UIViewRepresentable {
    let text: AttributedString
    var font: UIFont = .monospacedSystemFont(ofSize: 13, weight: .regular)
    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.textColor = .label
        view.isEditable = false
        view.isSelectable = true
        view.backgroundColor = .systemBackground
        view.textContainerInset = UIEdgeInsets(top: 12, left: 12, bottom: 20, right: 12)
        view.alwaysBounceVertical = true
        return view
    }
    func updateUIView(_ view: UITextView, context: Context) {
        let result = NSMutableAttributedString(text)
        let fullRange = NSRange(location: 0, length: result.length)
        result.addAttribute(.font, value: font, range: fullRange)
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
