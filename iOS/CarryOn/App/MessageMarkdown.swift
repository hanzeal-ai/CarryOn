import SwiftUI
import MarkdownUI
import Highlightr
import CarryOnCore

struct MessageMarkdown: View {
    let text: String
    var artifacts: [JSONValue] = []
    var threadID: String = ""
    @State private var selectedArtifact: JSONValue?
    @State private var previewID = UUID()
    var body: some View {
        Markdown(text)
            .markdownImageProvider(AttachmentImageProvider())
            .markdownInlineImageProvider(AttachmentInlineImageProvider())
            .markdownTextStyle { FontSize(15); ForegroundColor(Design.ink) }
            .markdownTextStyle(\.link) { ForegroundColor(Design.green) }
            .markdownBlockStyle(\.codeBlock) { configuration in
                CodeBlockView(code: configuration.content, language: configuration.language)
                    .markdownMargin(top: 8, bottom: 8)
            }
            .textSelection(.enabled)
            .environment(\.openURL, OpenURLAction { url in
                if url.scheme == "carryon-artifact", let ref = artifacts.first(where: { url.absoluteString == "carryon-artifact:" + $0["id"].text }) {
                    selectedArtifact = ref; previewID = UUID(); return .handled
                }
                return ["https", "http", "mailto"].contains(url.scheme?.lowercased() ?? "") ? .systemAction : .discarded
            })
            .background {
                if let selectedArtifact {
                    ArtifactView(ref: selectedArtifact, threadID: threadID, openOnLoad: true).id(previewID)
                }
            }
    }
}

struct CodeBlockView: View {
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
        }.background(Design.background, in: RoundedRectangle(cornerRadius: 10))
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .task(id: label + "\n" + code) {
                highlighted = nil
                let result = await CodeHighlight.shared.render(code, language: label)
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
    func render(_ code: String, language: String) -> AttributedString? {
        guard code.utf8.count <= CodeDocument.highlightLimit, language != "plaintext",
              let result = engine?.highlight(code, as: language, fastRender: true) else { return nil }
        return try? AttributedString(result, including: \.uiKit)
    }
}

struct CodeFilePreview: View {
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
            .task(id: document.id) {
                let result = await CodeHighlight.shared.render(document.text, language: document.language)
                if !Task.isCancelled { highlighted = result }
            }
        }
    }
}

/// TextKit handles long files without creating a SwiftUI view for every line.
private struct SourceTextView: UIViewRepresentable {
    let text: AttributedString
    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false
        view.isSelectable = true
        view.backgroundColor = .systemBackground
        view.textContainerInset = UIEdgeInsets(top: 12, left: 12, bottom: 20, right: 12)
        view.alwaysBounceVertical = true
        return view
    }
    func updateUIView(_ view: UITextView, context: Context) {
        let result = NSMutableAttributedString(text)
        result.addAttribute(.font, value: UIFont.monospacedSystemFont(ofSize: 13, weight: .regular), range: NSRange(location: 0, length: result.length))
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
