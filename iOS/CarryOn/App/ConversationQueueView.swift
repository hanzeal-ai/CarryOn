import SwiftUI
import CarryOnCore

struct ConversationQueueView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ConversationActionTarget
    @State private var editing: JSONValue = .null
    @State private var editText = ""
    @State private var editFingerprint: JSONValue = .null
    @State private var showingEditor = false
    @State private var failure: String?
    private var queue: JSONValue { model.snapshot(for: target)["queue"] }
    private var messages: [JSONValue] { queue["messages"].array }
    var body: some View {
        NavigationStack {
            List {
                if !model.canPerform(target) { Text("当前会话不可操作").foregroundStyle(Design.secondary) }
                if let failure { Text(failure).foregroundStyle(.red) }
                if let queueError = queue["error"].string { Text(queueError).foregroundStyle(.red) }
                else if queue == .null { Text("队列状态未知").foregroundStyle(Design.secondary) }
                else if messages.isEmpty { Text("暂无排队消息").foregroundStyle(Design.secondary) }
                ForEach(messages, id: \.stableID) { message in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(message["text"].text.isEmpty ? "图片消息" : message["text"].text).lineLimit(4).textSelection(.enabled)
                        let images = message["context"]["imageAttachments"].array
                        if !images.isEmpty {
                            ScrollView(.horizontal) { HStack {
                                ForEach(images, id: \.stableID) { image in
                                    MessageImage(part: .object(["type": .string("image"), "url": image["src"]]), threadID: target.threadID)
                                }
                            } }
                        }
                        HStack {
                            ConversationStatusLabel(state: .init(message["pausedReason"] == .null ? "等待发送" : "队列已暂停", "text.badge.clock", .waiting))
                            Spacer()
                            if message["pausedReason"] != .null {
                                Button("恢复") { submit("queue-resume", fields: ["messageId": message["id"]]) }.buttonStyle(.borderless).disabled(!model.canPerform(target, action: "queue-resume"))
                            }
                            Menu {
                                Button("编辑", systemImage: "pencil") {
                                    editing = message; editText = message["text"].text; editFingerprint = queue["fingerprint"]; showingEditor = true
                                }
                                Button("删除", systemImage: "trash", role: .destructive) { submit("queue-delete", fields: ["messageId": message["id"]]) }
                            } label: { Image(systemName: "ellipsis").frame(width: 44, height: 44) }.accessibilityLabel("排队消息操作").disabled(!model.canPerform(target, action: "queue-edit"))
                        }
                    }.disabled(!model.canPerform(target)).padding(.vertical, 4)
                }.onMove { source, destination in
                    var ids = messages.map { $0["id"] }; ids.move(fromOffsets: source, toOffset: destination)
                    submit("queue-reorder", fields: ["messageIds": .array(ids)])
                }.moveDisabled(!model.canPerform(target, action: "queue-reorder"))
            }.navigationTitle("消息队列").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) { EditButton().disabled(!model.canPerform(target, action: "queue-reorder") || messages.count < 2) }
                    ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
                }
                .sheet(isPresented: $showingEditor) {
                    NavigationStack {
                        VStack(alignment: .leading, spacing: 12) {
                            if let failure {
                                Text(failure).font(.caption).foregroundStyle(.red)
                                if let current = messages.first(where: { $0["id"] == editing["id"] }) {
                                    Text("当前排队内容：" + (current["text"].text.isEmpty ? "图片消息" : current["text"].text)).font(.caption).lineLimit(4)
                                    Button("已核对，使用最新队列重试") { editFingerprint = queue["fingerprint"]; self.failure = nil }
                                } else { Text("这条消息已不在队列中").font(.caption).foregroundStyle(Design.secondary) }
                            }
                            TextEditor(text: $editText)
                        }.padding().navigationTitle("编辑排队消息").navigationBarTitleDisplayMode(.inline)
                            .toolbar {
                                ToolbarItem(placement: .cancellationAction) { Button("取消") { showingEditor = false } }
                                ToolbarItem(placement: .confirmationAction) {
                                    Button("保存") {
                                        submit("queue-edit", fields: ["messageId": editing["id"], "prompt": .string(editText)], fingerprint: editFingerprint)
                                    }.disabled(!model.canPerform(target, action: "queue-edit") || editText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !messages.contains(where: { $0["id"] == editing["id"] }))
                                }
                            }
                    }
                }
        }.presentationDetents([.medium, .large])
    }
    private func submit(_ action: String, fields: [String: JSONValue], fingerprint: JSONValue? = nil) {
        let version = fingerprint ?? queue["fingerprint"]
        Task {
            let ok = await model.perform(action, target: target, fields: fields.merging(["queueFingerprint": version]) { _, new in new })
            if ok { showingEditor = false; failure = nil } else { failure = model.error }
        }
    }
}

/// Actionable waiting states stay next to the composer, even while reading older messages.
struct ConversationActionBar: View {
    @Environment(AppModel.self) private var model
    let target: ConversationActionTarget
    @State private var showingQueue = false
    @State private var showingRequests = false
    private var snapshot: JSONValue { model.snapshot(for: target) }
    private var requests: [JSONValue] { snapshot["controls"]["requests"].array }
    var body: some View {
        let count = snapshot["queue"]["messages"].array.count
        let pending = max(requests.count, snapshot["pendingRequests"].array.count)
        let queueFailed = snapshot["queue"]["error"].string != nil
        if pending > 0 || count > 0 || queueFailed {
            HStack(spacing: 16) {
                if pending > 0 {
                    Button { showingRequests = true } label: {
                        Label("待回应 \(pending)", systemImage: "hand.raised").foregroundStyle(.orange)
                    }.accessibilityLabel("处理 \(pending) 项待回应请求")
                }
                if count > 0 || queueFailed {
                    Button { showingQueue = true } label: { Label(queueFailed ? "队列读取失败" : "待发送 \(count)", systemImage: queueFailed ? "exclamationmark.circle" : "text.badge.clock") }
                }
                Spacer(minLength: 0)
            }.font(.caption).padding(.horizontal, 16).frame(minHeight: 40)
                .onChange(of: model.activityRequestKey, initial: true) { _, key in
                    if let key, requests.contains(where: { $0.requestKey == key }) {
                        showingRequests = true; model.activityRequestKey = nil
                    }
                }
                .sheet(isPresented: $showingQueue) { ConversationQueueView(target: target) }
                .sheet(isPresented: $showingRequests) {
                    NavigationStack {
                        ScrollView { VStack(spacing: 16) {
                            ForEach(requests, id: \.requestKey) { request in NativeRequestView(request: request, target: target).id(request.requestKey) }
                            if pending > requests.count { Text("部分请求需在 Codex App 处理。").foregroundStyle(Design.secondary) }
                            if pending == 0 { Label("当前请求已处理", systemImage: "checkmark.circle") }
                        }.padding(16) }
                        .navigationTitle("待回应").navigationBarTitleDisplayMode(.inline)
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { showingRequests = false } } }
                    }.presentationDetents([.medium, .large])
                }
        }
    }
}
