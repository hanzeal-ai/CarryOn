import SwiftUI
import ExyteChat
import CarryOnCore

struct SideChatsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var chats: [Record] = []
    @State private var selected: Record?
    @State private var failure: String?
    @State private var loading = false
    private var scope: String { model.scope + "\n" + (model.selectedThread?.id ?? "") }
    var body: some View {
        NavigationStack {
            Group {
                if let selected, let parent = model.selectedThread?.id {
                    SideChatConversation(chat: selected, parentID: parent).id(scope + selected.id)
                } else {
                    List {
                        if let failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load() } }) }
                        ForEach(chats) { chat in Button(chat.title) { selected = chat } }
                        if chats.isEmpty && failure == nil {
                            BlankState(text: loading ? "正在查找临时聊天…" : "暂无临时聊天", loading: loading, symbol: "bubble.left.and.bubble.right")
                        }
                    }
                }
            }
            .navigationTitle(selected?.title ?? "临时聊天").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
                if chats.count > 1 {
                    ToolbarItem(placement: .topBarLeading) {
                        Menu("切换") { ForEach(chats) { chat in Button(chat.title) { selected = chat } } }
                    }
                }
            }
            .task(id: scope) { chats = []; selected = nil; loading = false; await load() }
        }
    }
    private func load() async {
        guard let parent = model.selectedThread?.id, !loading else { return }
        let capturedScope = scope
        loading = true; failure = nil
        defer { if capturedScope == scope { loading = false } }
        do {
            repeat {
                let value = try await model.deviceRequest("/api/side-chats?parentId=" + ConsoleAddress.component(parent))
                guard !Task.isCancelled, capturedScope == scope else { return }
                if let error = value["error"].string, !error.isEmpty { throw APIError(error) }
                guard case .array(let items) = value["chats"] else { throw APIError("临时聊天目录格式不正确") }
                chats = try items.map(Record.init)
                if value["scanning"].bool != true {
                    if chats.count == 1 { selected = chats.first }
                    break
                }
                try await Task.sleep(for: .seconds(1))
            } while !Task.isCancelled
        } catch { if !Task.isCancelled, capturedScope == scope { failure = error.localizedDescription } }
    }
}

private struct SideChatConversation: View {
    @Environment(AppModel.self) private var model
    let chat: Record
    let parentID: String
    @State private var history: JSONValue = .null
    @State private var messages: [ExyteChat.Message] = []
    @State private var failure: String?
    @State private var loading = false
    var body: some View {
        ChatView(messages: messages, didSendMessage: { _ in }, messageBuilder: { params in
            if let item = params.message.customData["entry"] as? JSONValue {
                ConversationTimelineRow(item: item, threadID: chat.id)
                    .padding(.horizontal, 16).padding(.vertical, 8)
            }
        }, inputViewBuilder: { _ in EmptyView() })
        .setAvailableInputs([])
        .showDateHeaders(false).showAvatar(false).showMessageMenuOnLongPress(false)
        .showScrollToBottomButton(true)
        .mainHeaderBuilder {
            VStack(spacing: 12) {
                Text("临时聊天 · 只读").font(.caption).foregroundStyle(Design.secondary)
                if let failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load() } }) }
                else if history == .null { ProgressView("正在读取临时聊天…") }
                else if messages.isEmpty { BlankState(text: "暂无会话记录", symbol: "bubble.left.and.bubble.right") }
            }.padding(16)
        }
        .carryOnChatAppearance()
        .environment(\.conversationContentContext, ConversationContentContext(parentID: parentID))
        .toolbar { ToolbarItem(placement: .bottomBar) { Button("刷新") { Task { await load() } }.disabled(loading) } }
        .task { await load() }
    }
    private func load() async {
        guard !loading, model.selectedThread?.id == parentID else { return }
        let scope = model.scope
        loading = true; failure = nil; defer { loading = false }
        do {
            let result = try await model.deviceRequest("/api/side-chats/\(ConsoleAddress.component(chat.id))/history?parentId=" + ConsoleAddress.component(parentID))
            guard !Task.isCancelled, scope == model.scope, model.selectedThread?.id == parentID else { return }
            guard case .array(let timeline) = result["timeline"] else { throw APIError("临时聊天消息格式不正确") }
            history = result
            messages = groupedTimeline(timeline).enumerated().map { index, item in
                var message = ExyteChat.Message(id: item.stableID,
                    user: .init(id: "timeline", name: "", avatarURL: nil, type: .system),
                    createdAt: Date(timeIntervalSince1970: Double(index)), attributedText: AttributedString(item["text"].text), customData: ["entry": item])
                message.triggerRedraw = UUID()
                return message
            }
        } catch { if !Task.isCancelled, scope == model.scope { failure = error.localizedDescription } }
    }
}
