import SwiftUI
import CarryOnCore

struct ConversationChangesView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let threadID: String
    @State private var selectedEntry: JSONValue?
    private var history: JSONValue { model.history["thread"]["id"].text == threadID ? model.history : .null }
    var body: some View {
        NavigationStack {
            List {
                if history["historyWindow"]["hasMore"].bool == true || history["truncated"].bool == true {
                    Text("仅显示当前已加载记录中的改动").font(.caption).foregroundStyle(Design.secondary)
                }
                ForEach(ConversationChanges.files(history)) { file in
                    NavigationLink {
                        List {
                            ForEach(Array(file.entries.enumerated()), id: \.offset) { index, entry in
                                Button("第 \(index + 1) 次修改") { selectedEntry = entry }
                            }
                        }.navigationTitle((file.path as NSString).lastPathComponent)
                    } label: {
                        Label(file.path, systemImage: "doc.text").font(.subheadline)
                    }
                }
                ForEach(ConversationChanges.summaries(history), id: \.stableID) { item in
                    NavigationLink("本轮修改汇总") {
                        ScrollView { CodeBlockView(code: item["data"]["diff"].text, language: "diff").padding() }
                            .navigationTitle("修改汇总")
                    }
                }
                if !ConversationChanges.hasChanges(history) { Text("当前记录没有文件改动") }
            }.sheet(isPresented: Binding(get: { selectedEntry != nil }, set: { if !$0 { selectedEntry = nil } })) {
                if let selectedEntry { ExecutionDetailView(item: selectedEntry, threadID: threadID) }
            }.navigationTitle("查看改动").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }
}
