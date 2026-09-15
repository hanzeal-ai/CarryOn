import SwiftUI
import CarryOnCore

struct ExecutionDetailView: View {
    @Environment(\.dismiss) private var dismiss
    let item: JSONValue
    let threadID: String
    private var data: JSONValue { item["data"] }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        ConversationStatusLabel(state: .activity(item))
                        Spacer()
                        if let ms = data["durationMs"].int ?? item["durationMs"].int { Text(String(format: "%.1f 秒", Double(ms) / 1000)).font(.caption).foregroundStyle(Design.secondary) }
                    }
                    content
                    if item["supported"].bool == false { Text("此活动的完整内容请在 Codex App 查看。").font(.caption).foregroundStyle(Design.secondary) }
                }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            }.navigationTitle(item["title"].text.isEmpty ? "执行详情" : item["title"].text).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }
    @ViewBuilder private var content: some View {
        switch item["type"].text {
        case "commandExecution":
            if !data["cwd"].text.isEmpty { Label(data["cwd"].text, systemImage: "folder").font(.caption).textSelection(.enabled) }
            CodeBlockView(code: data["command"].text, language: "shell")
            Text("输出").font(.subheadline).bold()
            if data["aggregatedOutput"].text.isEmpty { Text(item["status"].text == "inProgress" ? "等待输出…" : "无输出").foregroundStyle(Design.secondary) }
            else { CodeBlockView(code: data["aggregatedOutput"].text, language: "plaintext") }
            if let exit = data["exitCode"].int { Text("退出码 \(exit)").font(.caption).foregroundStyle(exit == 0 ? Design.secondary : .red) }
        case "fileChange":
            ForEach(Array(data["changes"].array.enumerated()), id: \.offset) { _, change in
                VStack(alignment: .leading, spacing: 8) {
                    Label(change["path"].text, systemImage: "doc.text").font(.subheadline).textSelection(.enabled)
                    if !change["diff"].text.isEmpty { CodeBlockView(code: change["diff"].text, language: "diff") }
                    else { ConversationValueRows(value: change) }
                }
            }
        case "plan", "todo-list":
            if !data["explanation"].text.isEmpty { MessageMarkdown(text: data["explanation"].text) }
            if data["plan"].array.isEmpty { MessageMarkdown(text: data["text"].text) }
            ForEach(Array(data["plan"].array.enumerated()), id: \.offset) { _, step in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: ConversationState.status(step["status"].text).symbol).foregroundStyle(step["status"].text == "completed" ? .green : Design.secondary)
                    Text(step["step"].string ?? step["text"].text).textSelection(.enabled)
                }
            }
        case "mcpToolCall", "dynamicToolCall", "functionCallOutput":
            if data["arguments"] != .null { Text("参数").font(.subheadline).bold(); ConversationValueRows(value: data["arguments"]) }
            if data["error"] != .null { Text("错误").font(.subheadline).bold(); ConversationValueRows(value: data["error"]) }
            Text("结果").font(.subheadline).bold()
            let result = data["result"] != .null ? data["result"] : data["output"]
            let parts = result["content"].array + data["contentItems"].array
            if !parts.isEmpty {
                ForEach(Array(parts.enumerated()), id: \.offset) { _, part in
                    if !part["text"].text.isEmpty { CodeBlockView(code: part["text"].text, language: "plaintext") }
                    else if part["type"].text != "image" { ConversationValueRows(value: part) }
                }
            } else if let text = result.string { CodeBlockView(code: text, language: "plaintext") }
            else if result != .null { ConversationValueRows(value: result) }
            ForEach(item["artifacts"].array, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID, inlineImage: true) }
        case "reasoning":
            MessageMarkdown(text: item["text"].text)
        case "webSearch":
            Text(data["query"].text).textSelection(.enabled)
            ConversationValueRows(value: data["action"])
        default:
            if !item["text"].text.isEmpty { MessageMarkdown(text: item["text"].text) }
            ConversationValueRows(value: data)
        }
    }
}

struct ExecutionActivityRow: View {
    let item: JSONValue
    let threadID: String
    @State private var details = false
    var body: some View {
        Button { details = true } label: {
            HStack(spacing: 7) {
                let state = ConversationState.activity(item)
                Image(systemName: state.tone == .failure ? "exclamationmark.circle" : ConversationProcess.symbol(item))
                Text(ConversationPresentation.activityLabel(item, text: ConversationProcess.activitySummary(item))).lineLimit(1).multilineTextAlignment(.leading)
                if state.tone == .failure { Text("失败").foregroundStyle(.red) }
                Spacer(minLength: 0)
            }.font(.system(size: 13)).foregroundStyle(Design.secondary)
                .frame(maxWidth: .infinity, minHeight: 36, alignment: .leading).contentShape(Rectangle())
        }.buttonStyle(.plain)
            .sheet(isPresented: $details) { LiveExecutionDetail(item: item, threadID: threadID) }
    }
}

private struct LiveExecutionDetail: View {
    @Environment(AppModel.self) private var model
    @Environment(\.conversationContentContext) private var context
    let item: JSONValue
    let threadID: String
    var body: some View {
        let history = context.parentID == nil ? model.history : model.sideHistory
        let latest = history["thread"]["id"].text == threadID ? history["timeline"].array.first { $0.stableID == item.stableID } : nil
        ExecutionDetailView(item: latest ?? item, threadID: threadID)
    }
}
