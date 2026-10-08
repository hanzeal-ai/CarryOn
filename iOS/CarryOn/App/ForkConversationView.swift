import SwiftUI
import CarryOnCore

struct ForkConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let thread: Record
    let scope: String
    var autoCreate = false
    var completed: () -> Void
    @State private var launched = false
    @State private var lastTurnID = ""
    @State private var submitting = false
    @State private var failure: String?
    private var current: Bool { scope == model.scope && model.selectedThread?.id == thread.id }
    private var turns: [JSONValue] {
        var seen = Set<String>()
        return model.history["timeline"].array.filter {
            guard $0["type"].text == "userMessage", let id = $0["turnId"].string,
                  id != model.history["controls"]["activeTurnId"].string else { return false }
            return seen.insert(id).inserted
        }
    }
    private var validTurn: Bool { lastTurnID.isEmpty || turns.contains { $0["turnId"].text == lastTurnID } }
    var body: some View {
        NavigationStack {
            Form {
                if let failure { Text(failure).foregroundStyle(.red).accessibilityIdentifier("fork-error") }
                Text("在新会话中继续，保留原会话。分叉不会自动发送消息。")
                    .font(.subheadline).foregroundStyle(Design.secondary)
                Picker("保留到", selection: $lastTurnID) {
                    Text("当前完整历史").tag("")
                    if !validTurn { Text("此前轮次已不可用，请重新选择").tag(lastTurnID).disabled(true) }
                    ForEach(turns, id: \.stableID) { turn in
                        Text(String(turn["text"].text.prefix(80))).tag(turn["turnId"].text)
                    }
                }
                if model.history["historyWindow"]["hasMore"].bool == true {
                    Text("轮次列表仅包含已加载历史；完整历史选项保留全部历史。")
                        .font(.caption).foregroundStyle(Design.secondary)
                }
            }.navigationTitle("分叉会话").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(submitting) }
                    ToolbarItem(placement: .confirmationAction) {
                        Button(submitting ? "正在分叉…" : "创建分叉") { Task { await fork() } }
                            .disabled(submitting || !current || !validTurn || !model.canWrite(.create) || model.state != "idle")
                    }
                }
        }.interactiveDismissDisabled(submitting)
            .task { if autoCreate, !launched { launched = true; await fork() } }
    }
    private func fork() async {
        guard current, !submitting, validTurn, model.canWrite(.create), model.state == "idle", model.history["controls"]["supportedOperations"].array.contains(.string("fork")) else { failure = "当前会话暂不可分叉"; return }
        submitting = true; failure = nil; defer { submitting = false }
        let body: JSONValue = lastTurnID.isEmpty ? .object([:]) : .object(["lastTurnId": .string(lastTurnID)])
        let accepted = await model.write(path: "/api/threads/" + ConsoleAddress.component(thread.id) + "/fork", target: thread.id, body: body) { job in
            guard current, let id = job["createdThreadId"].string,
                  let record = try? Record(.object(["id": .string(id), "title": .string(thread.title)])) else { return }
            dismiss(); completed(); model.open(record)
        }
        if !accepted, current { failure = model.error ?? "未能确认分叉，请在请求记录中核对" }
    }
}
