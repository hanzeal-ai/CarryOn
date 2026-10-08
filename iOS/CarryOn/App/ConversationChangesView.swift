import SwiftUI
import CarryOnCore

struct ConversationChangesView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let threadID: String
    var scopedHistory: JSONValue? = nil
    var filePath: String? = nil
    @State private var wrapLines = false
    @State private var selectedPath: String?
    @State private var projection: ConversationChanges.Snapshot?
    @State private var commentLine: UnifiedDiff.Line?
    @State private var commentPath = ""
    @State private var commentText = ""
    @State private var commentScope = ""
    @State private var reviewScope: String?
    @State private var commentSourceID = ""
    @State private var commentPatch = ""
    @State private var editingComment: ReviewComment?
    private var draftKey: String { (reviewScope ?? "") + "\n" + threadID }
    private var current: Bool { reviewScope == model.scope && model.selectedThread?.id == threadID }
    private func comments(for source: String, patch: String, path: String) -> [ReviewComment] {
        let comments = model.draftStore.comments[draftKey] ?? []
        guard current, !comments.isEmpty else { return [] }
        let digest = ReviewComment.patchIdentity(patch)
        return comments.filter { $0.sourceID == source && $0.patchID == digest && $0.path == path }
    }
    private var history: JSONValue { scopedHistory ?? (model.history["thread"]["id"].text == threadID ? model.history : .null) }
    private var selectedFile: ConversationChanges.File? {
        let files = projection?.files ?? []
        return files.first { $0.path == (selectedPath ?? filePath) } ?? files.first
    }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if history["historyWindow"]["hasMore"].bool == true || history["truncated"].bool == true {
                        Text("仅显示当前已加载记录中的改动").font(.caption).foregroundStyle(Design.secondary)
                    }
                    if projection == nil {
                        ProgressView("正在读取改动…")
                    } else if let file = selectedFile {
                        Text(file.path).font(.caption).foregroundStyle(Design.secondary).textSelection(.enabled)
                        ForEach(Array(file.entries.enumerated()), id: \.offset) { index, entry in
                            VStack(alignment: .leading, spacing: 8) {
                                if file.entries.count > 1 {
                                    Text("第 \(index + 1) 次修改").font(.subheadline.weight(.medium))
                                }
                                if ["failed", "declined"].contains(entry["status"].text) {
                                    ConversationStatusLabel(state: .activity(entry))
                                }
                                let change = entry["data"]["changes"].array.first ?? .null
                                let sourceID = entry["id"].string ?? entry["nativeId"].string ?? ""
                                if !change["diff"].text.isEmpty {
                                    UnifiedDiffView(patch: change["diff"].text, filePath: file.path, wrapLines: wrapLines,
                                                    comments: comments(for: sourceID, patch: change["diff"].text, path: file.path),
                                                    editComment: { editingComment = $0 }, removeComment: removeComment,
                                                    comment: current && !sourceID.isEmpty ? { line in
                                        commentScope = model.scope; commentPath = file.path
                                        commentSourceID = sourceID; commentPatch = change["diff"].text
                                        commentText = ""; commentLine = line
                                    } : nil)
                                } else {
                                    Text("此文件没有可展示的文本 diff").font(.subheadline).foregroundStyle(Design.secondary)
                                }
                            }
                        }
                    } else if let projection, !projection.summaries.isEmpty {
                        ForEach(projection.summaries, id: \.stableID) { item in
                            UnifiedDiffView(patch: item["data"]["diff"].text, wrapLines: wrapLines)
                        }
                    } else {
                        Text("当前记录没有文件改动")
                    }
                }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            }.id(selectedFile?.path)
                .navigationTitle("文件改动").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        if let file = selectedFile {
                            Menu {
                                ForEach(projection?.files ?? []) { option in
                                    Button { selectedPath = option.path } label: {
                                        if option.path == file.path {
                                            Label(option.path, systemImage: "checkmark")
                                        } else {
                                            Text(option.path)
                                        }
                                    }
                                }
                            } label: {
                                HStack(spacing: 4) {
                                    Text((file.path as NSString).lastPathComponent).lineLimit(1).truncationMode(.middle)
                                    Image(systemName: "chevron.down")
                                }
                            }.accessibilityLabel("切换文件").accessibilityValue(file.path)
                        }
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { wrapLines.toggle() } label: { Image(systemName: "arrow.turn.down.left") }
                            .accessibilityLabel("自动换行").accessibilityValue(wrapLines ? "已开启" : "已关闭")
                            .accessibilityAddTraits(wrapLines ? .isSelected : [])
                    }
                    ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
                }
                .onAppear { if reviewScope == nil { reviewScope = model.scope } }
                .task(id: ChangesSource(scope: model.scope, threadID: threadID,
                                        revision: scopedHistory == nil ? model.historyRevision : 0,
                                        scopedHistory: scopedHistory)) {
                    let source = history
                    let result = await Task.detached(priority: .userInitiated) { ConversationChanges.Snapshot(source) }.value
                    if !Task.isCancelled { projection = result }
                }
                .sheet(item: $commentLine) { line in
                    NavigationStack {
                        Form {
                            Section(commentPath + " · " + (line.location ?? "")) {
                                Text(line.text).font(.caption.monospaced()).textSelection(.enabled)
                                TextField("添加评论…", text: $commentText, axis: .vertical).lineLimit(3...8)
                            }
                        }.navigationTitle("评论改动").navigationBarTitleDisplayMode(.inline)
                            .toolbar {
                                ToolbarItem(placement: .cancellationAction) { Button("取消") { commentLine = nil } }
                                ToolbarItem(placement: .confirmationAction) {
                                    Button("添加评论") {
                                        addComment(line)
                                    }.disabled(!current || commentScope != model.scope || commentText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                                }
                            }
                    }
                }
                .sheet(item: $editingComment) { note in
                    ReviewCommentEditor(comment: note) { updated in
                        guard current, let index = model.draftStore.comments[draftKey]?.firstIndex(where: { $0.id == updated.id }),
                              model.draftStore.comments[draftKey]?[index] == note else { return false }
                        model.draftStore.comments[draftKey]?[index] = updated
                        return true
                    }
                }
        }
    }
    private func addComment(_ line: UnifiedDiff.Line) {
        guard current, commentScope == model.scope,
              let note = ReviewComment(sourceID: commentSourceID, path: commentPath, patch: commentPatch, line: line, text: commentText) else { return }
        model.draftStore.comments[draftKey, default: []].append(note)
        model.draftStore.save(); commentLine = nil
    }
    private func removeComment(_ note: ReviewComment) {
        guard current else { return }
        model.draftStore.comments[draftKey]?.removeAll { $0.id == note.id }
    }

}

private struct ChangesSource: Equatable {
    let scope: String
    let threadID: String
    let revision: Int
    let scopedHistory: JSONValue?
}

struct ConversationChangesCard: View {
    let history: JSONValue
    let projection: ConversationChanges.Snapshot
    let threadID: String
    @State private var reviewing = false
    @State private var expanded = false
    @State private var selectedFile: String?
    private var files: [ConversationChanges.File] { projection.files }
    private var totals: ConversationChanges.LineCounts? { projection.totals }
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "doc.badge.plus").font(.title3)
                    .frame(width: 38, height: 38).background(Design.background, in: RoundedRectangle(cornerRadius: 10))
                VStack(alignment: .leading, spacing: 3) {
                    Text(files.isEmpty ? "文件改动" : "已编辑 \(files.count) 个文件").font(.subheadline.weight(.medium))
                    if let totals { counts(totals) }
                }
                Spacer(minLength: 4)
                Button { selectedFile = nil; reviewing = true } label: {
                    Text("审核").font(.subheadline).padding(.horizontal, 12).padding(.vertical, 7)
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Design.border, lineWidth: 1))
                        .frame(minHeight: 44)
                }.buttonStyle(.plain)
                    .accessibilityLabel("审核文件改动")
            }.padding(12)
            ForEach(expanded ? files : Array(files.prefix(3))) { file in
                Divider()
                Button { selectedFile = file.path; reviewing = true } label: {
                    HStack(spacing: 10) {
                        Text(file.path).font(.caption).lineLimit(2).truncationMode(.middle)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 4)
                        if let count = file.lineCounts { counts(count) }
                    }.padding(.vertical, 8).frame(minHeight: 44).padding(.horizontal, 12).contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityLabel("查看 \(file.path) 的改动")
            }
            if files.count > 3 {
                Divider()
                Button { expanded.toggle() } label: {
                    HStack {
                        Text(expanded ? "收起" : "展开其余 \(files.count - 3) 个文件")
                        Spacer()
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                    }.font(.caption).padding(.horizontal, 12).frame(minHeight: 44).contentShape(Rectangle())
                }.buttonStyle(.plain).accessibilityValue(expanded ? "已展开" : "已收起")
            }
            if history["historyWindow"]["hasMore"].bool == true || history["truncated"].bool == true {
                Text("仅统计已加载的改动记录").font(.caption2).foregroundStyle(Design.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(12)
            }
        }.foregroundStyle(Design.ink)
            .background(Design.surface, in: RoundedRectangle(cornerRadius: 14))
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Design.border, lineWidth: 1))
            .sheet(isPresented: $reviewing, onDismiss: { selectedFile = nil }) {
                ConversationChangesView(threadID: threadID, scopedHistory: history, filePath: selectedFile)
            }
    }
    private func counts(_ value: ConversationChanges.LineCounts) -> some View {
        HStack(spacing: 5) {
            Text("+\(value.added)").foregroundStyle(Design.green)
            Text("-\(value.removed)").foregroundStyle(.red)
        }.font(.caption.monospacedDigit()).fixedSize()
            .accessibilityLabel("新增 \(value.added) 行，删除 \(value.removed) 行")
    }
}
