import SwiftUI
import CarryOnCore

struct UnifiedDiffView: View {
    let patch: String
    var comment: ((UnifiedDiff.Line) -> Void)? = nil
    @State private var lines: [UnifiedDiff.Line] = []
    var body: some View {
        GeometryReader { geometry in
        ScrollView([.vertical, .horizontal]) {
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(lines) { line in
                    HStack(alignment: .top, spacing: 8) {
                        Text(line.old.map(String.init) ?? "").frame(width: 38, alignment: .trailing).foregroundStyle(Design.secondary)
                        Text(line.new.map(String.init) ?? "").frame(width: 38, alignment: .trailing).foregroundStyle(Design.secondary)
                        Text(line.text.isEmpty ? " " : line.text).fixedSize(horizontal: true, vertical: false).textSelection(.enabled)
                        Spacer(minLength: 8)
                    }.font(.system(.caption, design: .monospaced)).padding(.vertical, 3)
                        .frame(minWidth: geometry.size.width, maxWidth: .infinity, alignment: .leading)
                        .background { Rectangle().fill(line.kind == .added ? Design.green.opacity(0.12) : line.kind == .removed ? Color.red.opacity(0.10) : Color.clear) }
                        .contextMenu {
                            if line.location != nil, let comment {
                                Button("评论此行", systemImage: "text.bubble") { comment(line) }
                            }
                            Button("复制", systemImage: "doc.on.doc") { UIPasteboard.general.string = line.text }
                        }
                }
            }
        }
        }.frame(height: min(max(CGFloat(lines.count) * 24, 80), 500))
            .background(Design.surface, in: RoundedRectangle(cornerRadius: 8))
            .task(id: patch) {
                let source = patch
                let result = await Task.detached(priority: .userInitiated) { UnifiedDiff.lines(source) }.value
                if !Task.isCancelled { lines = result }
            }
    }
}
