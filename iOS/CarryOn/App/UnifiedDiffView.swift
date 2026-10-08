import SwiftUI
import CarryOnCore

struct UnifiedDiffView: View {
    let patch: String
    var filePath: String? = nil
    var wrapLines = false
    var comments: [ReviewComment] = []
    var editComment: ((ReviewComment) -> Void)? = nil
    var removeComment: ((ReviewComment) -> Void)? = nil
    var comment: ((UnifiedDiff.Line) -> Void)? = nil
    @State private var lines: [UnifiedDiff.Line] = []
    @State private var highlighted: [Int: AttributedString] = [:]
    @State private var contentHeight: CGFloat = 80
    @State private var contentWidth: CGFloat = 0
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.colorScheme) private var colorScheme
    @ScaledMetric(relativeTo: .caption) private var lineNumberWidth: CGFloat = 32
    var body: some View {
        GeometryReader { geometry in
        ScrollView(wrapLines ? .vertical : [.vertical, .horizontal]) {
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(lines) { line in
                    VStack(alignment: .leading, spacing: 0) {
                    HStack(alignment: .top, spacing: 8) {
                        Text((line.new ?? line.old).map(String.init) ?? "").frame(width: lineNumberWidth, alignment: .trailing).foregroundStyle(Design.secondary)
                        Text(display(line)).fixedSize(horizontal: !wrapLines, vertical: wrapLines).textSelection(.enabled)
                            .background {
                                GeometryReader { text in
                                    Color.clear.preference(key: DiffTextWidth.self, value: text.size.width)
                                }
                            }
                        Spacer(minLength: 8)
                    }.font(.system(.caption, design: .monospaced)).padding(.vertical, 3)
                        .fixedSize(horizontal: !wrapLines, vertical: false)
                        .frame(minWidth: geometry.size.width, maxWidth: .infinity, alignment: .leading)
                        .background { Rectangle().fill(line.kind == .added ? Design.green.opacity(0.12) : line.kind == .removed ? Color.red.opacity(0.10) : Color.clear) }
                        .contextMenu {
                            if line.location != nil, let comment {
                                Button("评论此行", systemImage: "text.bubble") { comment(line) }
                            }
                            Button("复制", systemImage: "doc.on.doc") { UIPasteboard.general.string = line.text }
                        }
                        ForEach(comments.filter { $0.lineID == line.id }) { note in
                            DiffReviewCommentCard(comment: note, edit: { editComment?(note) }, remove: { removeComment?(note) })
                                .padding(12).frame(width: geometry.size.width, alignment: .leading)
                        }
                    }
                }
            }.frame(width: wrapLines ? geometry.size.width : max(geometry.size.width, contentWidth + lineNumberWidth + 2 * 8 + 8), alignment: .leading)
            .background {
                GeometryReader { content in
                    Color.clear.preference(key: DiffContentHeight.self, value: content.size.height)
                }
            }
        }
        }.frame(height: min(max(contentHeight, 80), 500))
            .onPreferenceChange(DiffContentHeight.self) { height in
                if abs(contentHeight - height) > 1 { contentHeight = height }
            }
            .onPreferenceChange(DiffTextWidth.self) { width in
                if !wrapLines && width > contentWidth + 1 { contentWidth = width }
            }
            .onChange(of: dynamicTypeSize) { _, _ in contentWidth = 0 }
            .background(Design.surface, in: RoundedRectangle(cornerRadius: 8))
            .task(id: patch) {
                let source = patch
                let result = await Task.detached(priority: .userInitiated) { UnifiedDiff.lines(source) }.value
                if !Task.isCancelled { contentWidth = 0; lines = result }
            }
            .task(id: DiffHighlightSource(patch: patch, filePath: filePath, dark: colorScheme == .dark)) {
                highlighted = [:]
                guard let filePath, let language = CodeDocument.language(filename: filePath) else { return }
                let result = await CodeHighlight.shared.diff(patch, language: language, dark: colorScheme == .dark)
                if !Task.isCancelled { highlighted = result }
            }
    }
    private func display(_ line: UnifiedDiff.Line) -> AttributedString {
        guard !line.text.isEmpty else { return AttributedString(" ") }
        if let colored = highlighted[line.id], String(colored.characters) == line.text { return colored }
        return AttributedString(line.text)
    }
}

private struct DiffHighlightSource: Equatable {
    let patch: String
    let filePath: String?
    let dark: Bool
}

private struct DiffTextWidth: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

private struct DiffContentHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}
