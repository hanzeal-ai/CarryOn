import SwiftUI
import ExyteChat
import CarryOnCore

struct SideChatsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var initialPrompt: String? = nil
    var sendInitialPrompt = false
    var onCreated: (() -> Void)? = nil
    @State private var launched = false
    @State private var initialApplied = false
    @State private var chats: [Record] = []
    @State private var selected: Record?
    @State private var failure: String?
    @State private var loading = false
    @State private var creating = false
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
            .safeAreaInset(edge: .top) { if selected != nil, let failure { Text(failure).font(.caption).foregroundStyle(.red).padding() } }
            .navigationTitle(selected?.title ?? "临时聊天").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    if selected?.value["canClose"].bool == true || model.history["controls"]["supportedOperations"].array.contains(.string("side-create")) {
                        Menu {
                            if let selected, selected.value["canClose"].bool == true {
                                Button("结束临时聊天", role: .destructive) { Task { await close(selected) } }
                                    .disabled(creating || !model.canWrite(.stop))
                            } else {
                                Button { Task { await create() } } label: { Label(creating ? "正在创建…" : "新建临时聊天", systemImage: "plus") }
                                    .disabled(creating || !model.canWrite(.create))
                            }
                        } label: { Image(systemName: "ellipsis").frame(width: 28, height: 28) }
                            .accessibilityLabel("临时聊天操作")
                    }
                }
                if selected != nil {
                    ToolbarItem(placement: .topBarLeading) { Button("列表") { selected = nil } }
                }
            }
            .task(id: scope) {
                chats = []; selected = nil; loading = false; await load()
                if !Task.isCancelled, initialPrompt != nil, !launched { launched = true; await create() }
            }
        }
    }
    private func create() async {
        guard let parent = model.selectedThread?.id, !creating else { return }
        let captured = scope
        creating = true; failure = nil
        defer { creating = false }
        var createdID: String?
        let ok = await model.write(path: "/api/threads/" + ConsoleAddress.component(parent) + "/side-chats", target: parent, body: .object([:])) { job in
            if scope == captured { createdID = job["createdThreadId"].string }
        }
        guard scope == captured else { return }
        if ok {
            await load()
            guard captured == scope, let createdID else { return }
            if let prompt = initialPrompt, !initialApplied {
                initialApplied = true
                let key = model.scope + "\nside:" + parent + ":" + createdID
                model.draftStore.texts[key] = prompt; model.draftStore.save()
                onCreated?()
                if sendInitialPrompt, !prompt.isEmpty {
                    let target = ConversationActionTarget(scope: model.scope, threadID: createdID, parentID: parent)
                    let sent = await model.write(path: target.path("compose"), target: createdID, body: target.body(["prompt": .string(prompt)]))
                    guard captured == scope else { return }
                    if sent, model.draftStore.texts[key] == prompt { model.draftStore.texts[key] = ""; model.draftStore.save() }
                    else if !sent { failure = model.error }
                }
            }
            selected = chats.first { $0.id == createdID }
        }
        else { failure = model.error }
    }
    private func close(_ chat: Record) async {
        guard let parent = model.selectedThread?.id, !creating else { return }
        let captured = scope
        creating = true
        defer { creating = false }
        let ok = await model.write(path: "/api/side-chats/" + ConsoleAddress.component(chat.id) + "/close", target: chat.id,
                                   body: .object(["parentId": .string(parent)]))
        guard scope == captured else { return }
        if ok { selected = nil; await load() }
        else { failure = model.error }
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
    @State private var interrupting = false
    @State private var showingModel = false
    @State private var selectionText: String?
    @State private var disclosureState = ConversationDisclosureState()
    @State private var tableUpdates: TableUpdateTransaction?
    @State private var bottomVisible = true
    @State private var renderRevision = 0
    private var target: ConversationActionTarget { .init(scope: model.scope, threadID: chat.id, parentID: parentID) }
    private var images: Binding<[String]> { Binding(get: { model.draftStore.images[draftKey] ?? [] }, set: { model.draftStore.images[draftKey] = $0; model.draftStore.save() }) }
    private var draftKey: String { model.scope + "\nside:" + parentID + ":" + chat.id }
    private var writable: Bool { model.canPerform(target) && !submitting }
    private var chatContent: some View {
        let scope = model.scope, epoch = model.epoch
        return ChatView(messages: messages, didSendMessage: { _ in }, messageBuilder: { params in
            if let item = params.message.customData["entry"] as? JSONValue {
                ConversationTimelineRow(item: item, threadID: chat.id)
                    .environment(\.preparedMessageMarkdown, params.message.customData["markdown"] as? ParsedMessageMarkdown)
                    .onLongPressGesture { if !CarryOnMessageAction.menuItems(for: params.message).isEmpty { params.showContextMenuClosure() } }
                    .padding(.horizontal, 16).padding(.vertical, item["type"].text == "processGroup" ? 2 : 8)
            }
        }, inputViewBuilder: { _ in
            CarryOnChatComposer(text: Binding(get: { model.draftStore.texts[draftKey] ?? "" }, set: { model.draftStore.texts[draftKey] = $0; model.draftStore.save() }),
                disabled: !writable, sendAllowed: model.allows(.send), stopAllowed: model.allows(.stop), hasImages: !images.wrappedValue.isEmpty, stopping: history["status"]["state"].text == "running",
                submitting: submitting && !interrupting,
                resuming: history["status"]["state"].text == "idle" && history["controls"]["lastTurnStatus"].text == "interrupted",
                send: { Task { await send() } },
                stop: { Task { await send(stopping: true) } },
                resume: { Task { _ = await model.perform("resume", target: target, fields: ["turnId": history["controls"]["lastTurnId"]]) } }) {
                    ConversationPhotoPicker(images: images, disabled: !writable || !model.allows(.send))
                    Spacer(minLength: 4)
                    Button { showingModel = true } label: {
                        HStack(spacing: 4) {
                            Text(ModelPresentation.name(history["controls"]["settings"]["model"].string ?? history["metadata"]["latestModel"].string ?? "默认模型", catalog: model.cachedValue("/api/models")))
                                .lineLimit(1).truncationMode(.middle)
                            Text(ModelPresentation.effort(history["controls"]["settings"]["effort"].string ?? history["metadata"]["latestReasoningEffort"].text))
                                .foregroundStyle(Design.secondary).lineLimit(1)
                        }.font(.subheadline).frame(minHeight: 44)
                    }.accessibilityLabel("模型与思考强度")
                }
        }, messageMenuAction: { (action: CarryOnMessageAction, _, message) in
            performMessageAction(action, messageID: message.id, scope: scope, epoch: epoch)
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
    }
    var body: some View {
        chatContent
        .sheet(isPresented: $showingModel) { ModelInformationView(target: target) }
        .sheet(isPresented: Binding(get: { selectionText != nil }, set: { if !$0 { selectionText = nil } })) {
            if let selectionText { MessageTextSelectionView(text: selectionText) }
        }
        .onChange(of: model.scope) { _, _ in selectionText = nil }
        .onChange(of: model.epoch) { _, _ in selectionText = nil }
        .onChange(of: model.sideThreadID) { _, _ in selectionText = nil }
        .onChange(of: model.selectedThread?.id) { _, _ in selectionText = nil }
        .onChange(of: model.allows(.view)) { _, allowed in if !allowed { selectionText = nil } }
        .environment(\.conversationContentContext, ConversationContentContext(parentID: parentID, isReadOnly: history["access"]["canInteract"].bool != true || history["access"]["nativeReady"].bool != true))
        .environment(\.conversationDisclosureState, disclosureState)
        .toolbar { ToolbarItem(placement: .topBarTrailing) {
            Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise").frame(width: 28, height: 28) }
                .disabled(loading).accessibilityLabel("刷新临时聊天")
        } }
        .task { model.watchSide(chat.id) }
        .onChange(of: model.sideHistory, initial: true) { _, value in
            if model.sideThreadID == chat.id && value["parentId"].string == parentID { render(value) }
        }
        .onChange(of: model.sideHistoryFailure) { _, value in failure = value }
        .onDisappear { renderRevision += 1; if model.sideThreadID == chat.id { model.watchSide(nil) } }
    }
    private func performMessageAction(_ action: CarryOnMessageAction, messageID: String, scope: String, epoch: UUID) {
        guard model.scope == scope, model.epoch == epoch, model.allows(.view),
              model.selectedThread?.id == parentID, model.sideThreadID == chat.id,
              history["parentId"].text == parentID,
              let message = messages.first(where: { $0.id == messageID }),
              let item = message.customData["entry"] as? JSONValue else { return }
        switch action {
        case .copy: UIPasteboard.general.string = item["text"].text
        case .selectText:
            let user = ["userMessage", "steeringUserMessage"].contains(item["type"].text)
            let text = user ? (item["displayText"].string ?? item["text"].text) : ConversationPresentation.attachmentDisplayText(item)
            selectionText = MessageTextSelectionView.plainText(text, resolveCreatedThreads: !user)
        case .edit: return
        }
    }
    private func send(stopping: Bool = false) async {
        guard writable, model.allows(stopping ? .stop : .send) else { return }
        let scope = model.scope, key = draftKey, text = model.draftStore.texts[draftKey] ?? ""
        let sentImages = images.wrappedValue
        guard stopping || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !sentImages.isEmpty else { return }
        submitting = true; interrupting = stopping
        defer { submitting = false; interrupting = false }
        let destination = target
        let ok: Bool
        if stopping {
            ok = await model.perform("interrupt", target: destination, fields: ["expectedTurnId": history["controls"]["activeTurnId"]])
        } else {
            ok = await model.write(path: destination.path("compose"), target: chat.id, body: destination.body(["prompt": .string(text), "images": .array(sentImages.map(JSONValue.string))]))
        }
        guard scope == model.scope, model.selectedThread?.id == parentID else { return }
        if ok {
            if !stopping && model.draftStore.texts[key] == text { model.draftStore.texts[key] = "" }
            if !stopping && model.draftStore.images[key] == sentImages { model.draftStore.images[key] = [] }
            model.draftStore.save()
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
            var next = grouped.enumerated().map { index, item in
                if let existing = previous[item.stableID], existing.customData["entry"] as? JSONValue == item { return existing }
                var message = ExyteChat.Message(id: item.stableID,
                    user: .init(id: "timeline", name: "", avatarURL: nil, type: .system),
                    createdAt: Date(timeIntervalSince1970: Double(index)), attributedText: AttributedString(item["text"].text), customData: ["entry": item])
                message.triggerRedraw = UUID(); return message
            }
            // Keep a bounded window of prepared trees, including newly loaded older rows.
            // Offscreen history remains plain data and parses lazily when its row appears.
            let prepending = !messages.isEmpty && grouped.first?.stableID != messages.first?.id
            let preparedRange = prepending ? 0..<min(120, next.count) : max(0, next.count - 120)..<next.count
            for index in next.indices {
                if !preparedRange.contains(index) { next[index].customData.removeValue(forKey: "markdown") }
                else if next[index].customData["markdown"] == nil {
                    next[index].customData["markdown"] = await MessageMarkdownParser.shared.prepare(grouped[index])
                }
            }
            guard revision == renderRevision else { return }
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
