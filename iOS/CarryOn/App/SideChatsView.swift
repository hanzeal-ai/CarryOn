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
    @State private var submitting = false
    @State private var showingModel = false
    @State private var disclosureState = ConversationDisclosureState()
    @State private var tableUpdates: TableUpdateTransaction?
    @State private var bottomVisible = true
    @State private var renderRevision = 0
    private var target: ConversationActionTarget { .init(scope: model.scope, threadID: chat.id, parentID: parentID) }
    private var images: Binding<[String]> { Binding(get: { model.attachments[draftKey] ?? [] }, set: { model.attachments[draftKey] = $0 }) }
    private var draftKey: String { model.scope + "\nside:" + parentID + ":" + chat.id }
    private var writable: Bool { model.canPerform(target) && !submitting }
    var body: some View {
        ChatView(messages: messages, didSendMessage: { _ in }, messageBuilder: { params in
            if let item = params.message.customData["entry"] as? JSONValue {
                ConversationTimelineRow(item: item, threadID: chat.id)
                    .onLongPressGesture { if !CarryOnMessageAction.menuItems(for: params.message).isEmpty { params.showContextMenuClosure() } }
                    .padding(.horizontal, 16).padding(.vertical, 8)
            }
        }, inputViewBuilder: { _ in
            CarryOnChatComposer(text: Binding(get: { model.drafts[draftKey] ?? "" }, set: { model.drafts[draftKey] = $0 }),
                disabled: !writable, hasImages: !images.wrappedValue.isEmpty, stopping: history["status"]["state"].text == "running",
                resuming: history["status"]["state"].text == "idle" && history["controls"]["lastTurnStatus"].text == "interrupted",
                send: { Task { await send() } }, queue: { Task { await send(queued: true) } },
                stop: { Task { await send(stopping: true) } },
                resume: { Task { _ = await model.perform("resume", target: target, fields: ["turnId": history["controls"]["lastTurnId"]]) } }) {
                    ConversationPhotoPicker(images: images, disabled: !writable)
                    Button { showingModel = true } label: { Image(systemName: "slider.horizontal.3").frame(width: 44, height: 44) }.accessibilityLabel("模型与思考强度")
                }
        }, messageMenuAction: { (_: CarryOnMessageAction, _, message) in
            if let item = message.customData["entry"] as? JSONValue { UIPasteboard.general.string = item["text"].text }
        })
        .setAvailableInputs([])
        .updateTransaction($tableUpdates)
        .onContentOffsetChange { bottomVisible = $0 <= 20 }
        .betweenListAndInputViewBuilder {
            VStack(spacing: 4) {
                ConversationStatusLabel(state: .session(model.sideHistory, connected: model.connected, readFailed: model.sideHistoryFailure != nil)).padding(.top, 4)
                ConversationActionBar(target: target)
                if !images.wrappedValue.isEmpty { ScrollView(.horizontal) { HStack {
                    ForEach(Array(images.wrappedValue.enumerated()), id: \.offset) { index, url in
                        DraftImageThumbnail(dataURL: url) {
                            guard images.wrappedValue.indices.contains(index), images.wrappedValue[index] == url else { return }
                            images.wrappedValue.remove(at: index)
                        }.disabled(!writable)
                    }
                }.padding(.horizontal, 16) } }
            }
        }
        .showDateHeaders(false).showAvatar(false).showMessageMenuOnLongPress(false)
        .showScrollToBottomButton(true)
        .mainHeaderBuilder {
            VStack(spacing: 12) {
                if history["historyWindow"]["hasMore"].bool == true {
                    Button("加载更早记录") { model.loadMoreSide() }.disabled(!model.connected)
                }
                if let failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load() } }) }
                else if history == .null { ProgressView("正在读取临时聊天…") }
                else if messages.isEmpty { BlankState(text: "暂无会话记录", symbol: "bubble.left.and.bubble.right") }
                ForEach(model.outgoingFor(chat.id), id: \.stableID) { item in
                    OutgoingMessageStatusView(item: item) { model.outgoing.removeValue(forKey: item["id"].text) }
                }

            }.padding(16)
        }
        .carryOnChatAppearance()
        .sheet(isPresented: $showingModel) { ModelInformationView(target: target) }
        .environment(\.conversationContentContext, ConversationContentContext(parentID: parentID, isReadOnly: history["access"]["canInteract"].bool != true || history["access"]["nativeReady"].bool != true))
        .environment(\.conversationDisclosureState, disclosureState)
        .toolbar { ToolbarItem(placement: .bottomBar) { Button("刷新") { Task { await load() } }.disabled(loading) } }
        .task { model.watchSide(chat.id) }
        .onChange(of: model.sideHistory, initial: true) { _, value in
            if model.sideThreadID == chat.id && value["parentId"].string == parentID { render(value) }
        }
        .onChange(of: model.sideHistoryFailure) { _, value in failure = value }
        .onDisappear { if model.sideThreadID == chat.id { model.watchSide(nil) } }
    }
    private func send(stopping: Bool = false, queued: Bool = false) async {
        guard writable else { return }
        let scope = model.scope, key = draftKey, text = model.drafts[draftKey] ?? ""
        let sentImages = images.wrappedValue
        guard stopping || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !sentImages.isEmpty else { return }
        submitting = true; defer { submitting = false }
        let destination = target
        let ok: Bool
        if stopping {
            ok = await model.perform("interrupt", target: destination, fields: ["expectedTurnId": history["controls"]["activeTurnId"]])
        } else if queued {
            ok = await model.perform("queue-add", target: destination, fields: ["prompt": .string(text), "images": .array(sentImages.map(JSONValue.string)), "queueFingerprint": history["queue"]["fingerprint"]])
        } else {
            ok = await model.write(path: destination.path("compose"), target: chat.id, body: destination.body(["prompt": .string(text), "images": .array(sentImages.map(JSONValue.string))]))
        }
        guard scope == model.scope, model.selectedThread?.id == parentID else { return }
        if ok {
            if !stopping && model.drafts[key] == text { model.drafts[key] = "" }
            if !stopping && model.attachments[key] == sentImages { model.attachments[key] = [] }
            failure = nil
        }
        else { failure = model.error }
    }
    private func render(_ result: JSONValue) {
        guard case .array(let timeline) = result["timeline"] else { return }
        history = result; failure = nil
        renderRevision += 1
        let revision = renderRevision
        Task { @MainActor in
            let grouped = await Task.detached(priority: .userInitiated) { ConversationProcess.timeline(timeline) }.value
            guard revision == renderRevision else { return }
            let previous = Dictionary(messages.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            let next = grouped.enumerated().map { index, item in
                if let existing = previous[item.stableID], existing.customData["entry"] as? JSONValue == item { return existing }
                var message = ExyteChat.Message(id: item.stableID,
                    user: .init(id: "timeline", name: "", avatarURL: nil, type: .system),
                    createdAt: Date(timeIntervalSince1970: Double(index)), attributedText: AttributedString(item["text"].text), customData: ["entry": item])
                message.triggerRedraw = UUID(); return message
            }
            if let tableUpdates { await tableUpdates(animationMode: bottomVisible ? .none : .keepStable) {
                if revision == renderRevision { messages = next }
            } }
            else { messages = next }
        }
    }
    private func load() async {
        guard !loading, model.selectedThread?.id == parentID else { return }
        let scope = model.scope
        loading = true; failure = nil; defer { loading = false }
        do {
            let result = try await model.deviceRequest("/api/side-chats/\(ConsoleAddress.component(chat.id))/history?parentId=" + ConsoleAddress.component(parentID))
            guard !Task.isCancelled, scope == model.scope, model.selectedThread?.id == parentID else { return }
            guard case .array = result["timeline"] else { throw APIError("临时聊天消息格式不正确") }
            guard model.sideThreadID == chat.id else { return }
            render(result)
        } catch { if !Task.isCancelled, scope == model.scope { failure = error.localizedDescription } }
    }
}
