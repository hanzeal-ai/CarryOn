import SwiftUI
import CarryOnCore

struct DiffReviewCommentCard: View {
    let comment: ReviewComment
    let edit: () -> Void
    let remove: () -> Void
    @Environment(\.dynamicTypeSize) private var dynamicType
    private var title: some View { Label("本地评论", systemImage: "text.bubble").font(.system(.subheadline, design: .monospaced).weight(.semibold)) }
    private var location: some View { Text("第 \(comment.location) 行").font(.caption.monospaced()).foregroundStyle(Design.secondary) }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Group {
                if dynamicType.isAccessibilitySize {
                    VStack(alignment: .leading, spacing: 8) { title; location }
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    HStack { title; Spacer(minLength: 8); location }
                }
            }.padding(16)
            Divider()
            Text(comment.text).font(.subheadline.monospaced()).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading).padding(16)
            HStack {
                Spacer()
                Button("编辑", action: edit).frame(minHeight: 44)
                Button("删除", action: remove).frame(minHeight: 44)
            }.font(.system(.subheadline, design: .monospaced)).tint(.primary).padding(.horizontal, 16).padding(.bottom, 8)
        }.background(Design.reviewCommentBackground, in: RoundedRectangle(cornerRadius: 16))
    }
}

struct ReviewCommentEditor: View {
    let comment: ReviewComment
    let save: (ReviewComment) -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var text: String
    @State private var stale = false
    init(comment: ReviewComment, save: @escaping (ReviewComment) -> Bool) {
        self.comment = comment; self.save = save; _text = State(initialValue: comment.text)
    }
    var body: some View {
        NavigationStack {
            Form {
                Section(comment.path + " · " + comment.location) {
                    Text(comment.lineText).font(.caption.monospaced()).textSelection(.enabled)
                    TextField("评论…", text: $text, axis: .vertical).lineLimit(3...8)
                }
                if stale { Text("工作区或会话已改变，评论未修改").foregroundStyle(.red) }
            }.navigationTitle("编辑评论").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("保存") {
                            var updated = comment; updated.text = text
                            if save(updated) { dismiss() } else { stale = true }
                        }.disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
        }
    }
}

struct ReviewCommentsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ConversationActionTarget
    @State private var editing: ReviewComment?
    private var key: String { target.scope + "\n" + target.threadID }
    private var current: Bool { model.scope == target.scope && model.selectedThread?.id == target.threadID }
    private var comments: [ReviewComment] { current ? model.draftStore.comments[key] ?? [] : [] }
    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    Text("评论随下一条消息发送，尚未提交给 Codex").font(.caption).foregroundStyle(Design.secondary)
                    ForEach(comments) { comment in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(comment.path).font(.caption).foregroundStyle(Design.secondary)
                            Text(comment.lineText).font(.caption.monospaced()).textSelection(.enabled)
                            DiffReviewCommentCard(comment: comment, edit: { editing = comment }, remove: {
                                guard current else { return }
                                model.draftStore.comments[key]?.removeAll { $0.id == comment.id }
                            }).disabled(!current)
                        }
                    }
                }.padding(16)
            }.navigationTitle("待发送评论").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .sheet(item: $editing) { comment in
                    ReviewCommentEditor(comment: comment) { updated in
                        guard current, let index = model.draftStore.comments[key]?.firstIndex(where: { $0.id == updated.id }),
                              model.draftStore.comments[key]?[index] == comment else { return false }
                        model.draftStore.comments[key]?[index] = updated
                        return true
                    }
                }
        }
    }
}
