import SwiftUI
import PhotosUI
import QuickLook
import CarryOnCore
import ExyteChat

struct ConversationView: View {
    @Environment(AppModel.self) private var model
    let thread: Record
    @State private var menu = false
    @State private var activity = false
    @State private var modelInfo = false
    @State private var visibleCount = 120
    @State private var bottomVisible = true
    @State private var photos: [PhotosPickerItem] = []
    private var images: [String] {
        get { model.draftImages }
        nonmutating set { model.draftImages = newValue }
    }
    @State private var loadingImages = false
    @State private var selectionGeneration = UUID()
    @State private var submitting = false
    private var actionTarget: ConversationActionTarget { .init(scope: model.scope, threadID: thread.id) }
    @State private var timeline: [JSONValue] = []
    @State private var projectedHistoryRevision = -1
    @State private var chatMessages: [ExyteChat.Message] = []
    @State private var tableUpdates: TableUpdateTransaction?
    @State private var disclosureState = ConversationDisclosureState()
    @State private var readingState: ConversationReadingState?
    @State private var restoreScroll: ScrollToParams?
    @State private var refreshingMessages = false
    @State private var messagesNeedRefresh = false
    private func refreshMessages() {
        messagesNeedRefresh = true
        guard !refreshingMessages else { return }
        refreshingMessages = true
        Task { @MainActor in
            defer { refreshingMessages = false }
            while messagesNeedRefresh {
                messagesNeedRefresh = false
                let revision = model.historyRevision
                if projectedHistoryRevision != revision {
                    let source = model.history["timeline"].array, scope = model.scope
                    let grouped = await Task.detached(priority: .userInitiated) {
                        ConversationProcess.timeline(source)
                    }.value
                    guard model.scope == scope, model.selectedThread?.id == thread.id else { return }
                    guard model.historyRevision == revision else { messagesNeedRefresh = true; continue }
                    timeline = grouped; projectedHistoryRevision = revision
                }
                let next = projectedMessages()
                guard next != chatMessages else { continue }
                if let tableUpdates {
                    // Serialize snapshots: overlapping transactions can consume each other's animation mode.
                    await tableUpdates(animationMode: bottomVisible ? .none : .keepStable) { chatMessages = next }
                } else { chatMessages = next }
            }
        }
    }
    private func projectedMessages() -> [ExyteChat.Message] {
        let previous = Dictionary(chatMessages.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let rows = Array(timeline.suffix(visibleCount))
        let supplemental: JSONValue = .object([
            "showEmpty": .bool(model.historyFailure == nil && model.history != .null && timeline.isEmpty),
            "syncing": model.history["syncing"], "readOnly": .bool(model.conversationReadOnly),
            "requests": model.history["controls"]["requests"], "pendingRequests": model.history["pendingRequests"],
            "queue": model.history["queue"], "outgoing": .array(model.visibleOutgoing)
        ])
        var statusMessage: ExyteChat.Message
        if let existing = previous["carryon:status"], existing.customData["supplemental"] as? JSONValue == supplemental {
            statusMessage = existing
        } else {
            statusMessage = ExyteChat.Message(id: "carryon:status", user: .init(id: "status", name: "", avatarURL: nil, type: .system),
                createdAt: .distantPast, text: "", customData: ["supplemental": supplemental])
            statusMessage.triggerRedraw = UUID()
        }
        statusMessage.createdAt = Date(timeIntervalSince1970: Double(rows.count))
        return rows.enumerated().map { index, item in
            let date = Date(timeIntervalSince1970: Double(index))
            if var message = previous[item.stableID], message.customData["entry"] as? JSONValue == item {
                message.createdAt = date
                return message
            }
            var message = ExyteChat.Message(id: item.stableID,
                user: .init(id: "timeline", name: "", avatarURL: nil, type: .system),
                createdAt: date, attributedText: AttributedString(item["text"].text), customData: ["entry": item])
            message.triggerRedraw = UUID()
            return message
        } + [statusMessage]
    }
    var body: some View {
        ChatView(messages: chatMessages, didSendMessage: { _ in }, messageBuilder: { params in
            messageRow(params)
        }, inputViewBuilder: { _ in
            composerView
        }, messageMenuAction: { (_: CarryOnMessageAction, _, message) in
            if let item = message.customData["entry"] as? JSONValue { UIPasteboard.general.string = item["text"].text }
        })
        .setAvailableInputs([.text])
        .updateTransaction($tableUpdates)
        .scrollTo(restoreScroll)
        .showDateHeaders(false)
        .showAvatar(false)
        .showMessageMenuOnLongPress(false)
        .showScrollToBottomButton(true)
        .keyboardDismissMode(.interactive)
        .mainHeaderBuilder { historyHeader }
        .enableLoadMoreOlderMessages(hasMoreToLoad: canLoadEarlier, handleClosure: loadEarlierMessages)
        .betweenListAndInputViewBuilder { composerAccessories }
        .onContentOffsetChange { offset in
            bottomVisible = offset <= 20
            readingState?.offset = max(0, offset)
            if bottomVisible { readingState?.anchorID = nil }
            if bottomVisible { markRead() }
        }
        .carryOnChatAppearance()
        .environment(\.conversationDisclosureState, disclosureState)
        .environment(\.conversationContentContext, ConversationContentContext(isReadOnly: model.conversationReadOnly))
        .navigationTitle(thread.title).navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(!model.threadParents.isEmpty)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                HStack(spacing: 8) {
                    if let parent = model.threadParents.last {
                        Button { model.returnToParentThread() } label: {
                            HStack(spacing: 4) {
                                Image(systemName: "chevron.left").fontWeight(.semibold)
                                Text(parent.title).lineLimit(1).truncationMode(.tail)
                                    .frame(maxWidth: 112, alignment: .leading)
                            }.font(.subheadline).frame(minHeight: 44)
                        }.foregroundStyle(Design.link).accessibilityLabel("返回主会话：" + parent.title)
                    }
                    if model.otherActivityCount > 0 {
                        Button { activity = true } label: {
                            Text(model.otherActivityCount > 99 ? "99+" : String(model.otherActivityCount))
                                .font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                                .padding(.horizontal, 7).frame(minWidth: 22, minHeight: 22)
                                .background(Design.blue, in: Capsule()).frame(minHeight: 44)
                        }.fixedSize().layoutPriority(1)
                            .accessibilityLabel("其他 \(model.otherActivityCount) 个会话待查看或处理")
                    }
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { menu = true } label: { Image(systemName: "ellipsis") }.accessibilityLabel("会话操作")
            }
        }
        .sheet(isPresented: $activity) { ConversationActivityView(currentThreadID: thread.id) }
        .task(id: model.scope + thread.id + String(model.workspaceRevision)) {
            do { try await model.refreshActivityCounts() }
            catch { model.report(error, operation: "刷新其他会话角标", blocking: false) }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            Group {
                HStack(spacing: 8) {
                    ConversationStatusLabel(state: .session(model.history, connected: model.connected, readFailed: model.historyFailure != nil))
                    if model.conversationReadOnly { Text("只读").font(.caption) }
                }
                    .font(.caption2).foregroundStyle(Design.secondary).padding(5)
            }
        }
        .sheet(isPresented: $menu) { ConversationMenu() }
        .sheet(isPresented: $modelInfo) { ModelInformationView(target: actionTarget) }
        .sheet(isPresented: Binding(get: { model.editingMessage != .null }, set: { if !$0 { model.cancelEditing() } })) {
            EditMessageView(item: model.editingMessage, threadID: thread.id, scope: model.scope)
        }
        .onChange(of: model.historyRevision, initial: true) { _, _ in
            if model.history["thread"]["id"].text == thread.id { readingState?.historyLimit = model.historyLimit }
            refreshMessages()
            if bottomVisible { markRead() }
        }
        .onChange(of: visibleCount) { _, _ in readingState?.visibleCount = visibleCount; refreshMessages() }
        .onChange(of: model.visibleOutgoing) { _, _ in refreshMessages() }
        .onChange(of: model.historyFailure) { _, _ in refreshMessages() }
        .onChange(of: model.conversationReadOnly) { _, _ in refreshMessages() }
        .onChange(of: photos) { _, selection in Task { await loadPhotos(selection) } }
        .onDisappear { selectionGeneration = UUID(); loadingImages = false }
        .onAppear {
            let state = model.readingState(for: thread.id)
            readingState = state; disclosureState = state.disclosure; visibleCount = state.visibleCount
            bottomVisible = state.offset <= 20
            if let anchor = state.anchorID { restoreScroll = ScrollToParams(messageID: anchor, position: .middle) }
            else if state.offset > 20 { restoreScroll = ScrollToParams(offset: state.offset) }
        }
    }
    private func messageRow(_ params: MessageBuilderParameters) -> some View {
        Group {
            if let item = params.message.customData["entry"] as? JSONValue {
                ConversationTimelineRow(item: item, threadID: thread.id)
                    .onLongPressGesture {
                        if !CarryOnMessageAction.menuItems(for: params.message).isEmpty { params.showContextMenuClosure() }
                    }
            } else if let snapshot = params.message.customData["supplemental"] as? JSONValue {
                supplementalRows(snapshot)
            }
        }.padding(.horizontal, 16).padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading)
    }
    @ViewBuilder private var composerView: some View {
        @Bindable var model = model
        if !model.conversationReadOnly {
        CarryOnChatComposer(text: $model.draft,
            disabled: !model.canInteract || loadingImages || submitting,
            hasImages: !images.isEmpty, stopping: model.state == "running",
            resuming: model.state == "idle" && model.history["controls"]["lastTurnStatus"].text == "interrupted" && model.editingMessage == .null,
            send: submitMessage,
            queue: { Task { await send(queued: true) } },
            stop: interruptTurn,
            resume: { Task { _ = await model.operation("resume", fields: ["turnId": model.history["controls"]["lastTurnId"]]) } }) {
                PhotosPicker(selection: $photos, maxSelectionCount: max(1, 3 - images.count), matching: .images) {
                    Image(systemName: "plus").frame(width: 44, height: 44)
                }.disabled(!model.canInteract || !["idle", "running", "waiting"].contains(model.state) || model.editingMessage != .null || images.count >= 3 || loadingImages || submitting)
                    .accessibilityLabel("添加图片")
                Button { modelInfo = true } label: { Image(systemName: "slider.horizontal.3").offset(x: -6).frame(width: 44, height: 44) }
                    .accessibilityLabel("模型与思考强度")
            }
        }
    }
    private func submitMessage() {
        Task { await send() }
    }
    private func interruptTurn() {
        Task {
            _ = await model.operation("interrupt", fields: ["expectedTurnId": model.history["controls"]["activeTurnId"]])
        }
    }
    private var historyHeader: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let failure = model.historyFailure, model.history == .null {
                BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { model.retryHistory() })
            } else if model.history == .null {
                BlankState(text: model.device?.value["online"].bool == false ? "工作区已离线" : "正在加载会话…", loading: model.device?.value["online"].bool != false, symbol: "wifi.slash")
            }
            if let failure = model.historyFailure, model.history != .null {
                HStack {
                    Text(failure).font(.caption).foregroundStyle(Design.secondary); Spacer(); Button("重试") { model.retryHistory() }
                }
            }
            if model.historyFailure == nil && model.history["syncing"].bool == true && !timeline.isEmpty {
                Text("已显示本地记录，正在同步原生历史").font(.caption).foregroundStyle(Design.secondary)
            }

        }.padding(.horizontal, 16)
    }
    private var canLoadEarlier: Bool {
        timeline.count > visibleCount || (model.connected && model.historyFailure == nil
            && model.historyLimit < 100000 && model.history["historyWindow"]["hasMore"].bool == true)
    }
    private func loadEarlierMessages() async {
        guard canLoadEarlier else { return }
        bottomVisible = false
        if timeline.count > visibleCount { visibleCount += 120; return }
        let scope = model.scope, threadID = thread.id
        visibleCount += 120
        model.loadEarlierHistory()
        let limit = model.historyLimit
        // Keep pagination in flight until the expanded stream window arrives.
        for _ in 0..<150 {
            guard !Task.isCancelled, model.scope == scope, model.selectedThread?.id == threadID else { return }
            if (model.history["historyWindow"]["limit"].int ?? 0) >= limit || model.historyFailure != nil { return }
            do { try await Task.sleep(for: .milliseconds(100)) } catch { return }
        }
        model.historyFailure = "更早记录加载超时，请重试"
    }
    private func supplementalRows(_ snapshot: JSONValue) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if snapshot["showEmpty"].bool == true && snapshot["outgoing"].array.isEmpty {
                BlankState(
                    text: snapshot["syncing"].bool == true ? "正在同步会话…" : "暂无会话记录", loading: snapshot["syncing"].bool == true, symbol: "bubble.left.and.bubble.right")
            }
            ForEach(snapshot["outgoing"].array, id: \.stableID) { item in
                OutgoingMessageStatusView(item: item) { model.outgoing.removeValue(forKey: item["id"].text) }
            }


        }
    }
    private var composerAccessories: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !model.conversationReadOnly { ConversationActionBar(target: actionTarget) }
            if loadingImages || submitting { ProgressView().controlSize(.small) }
            if !model.conversationReadOnly && !images.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(Array(images.enumerated()), id: \.offset) { index, url in
                            DraftImageThumbnail(dataURL: url) {
                                guard images.indices.contains(index), images[index] == url else { return }
                                images.remove(at: index)
                            }.disabled(submitting || loadingImages)
                        }
                    }.padding(.vertical, 6)
                }
            }
        }.padding(.horizontal, 16)
    }
    private func send(queued: Bool = false) async {
        guard !submitting, model.canInteract, !loadingImages else { return }
        submitting = true; defer { submitting = false }
        if await model.compose(images: images.map(JSONValue.string), queued: queued) { photos = [] }
    }
    private func markRead() {
        let sequence = model.readSequence
        Task { await model.markDisplayed(threadID: thread.id, sequence: sequence) }
    }
    private func loadPhotos(_ selection: [PhotosPickerItem]) async {
        guard !selection.isEmpty else { return }
        let generation = UUID(); selectionGeneration = generation
        loadingImages = true; defer { if selectionGeneration == generation { loadingImages = false } }
        do {
            let result = try await conversationPhotos(selection)
            if selectionGeneration == generation { images = Array((images + result).prefix(3)); photos = [] }
        } catch { if selectionGeneration == generation { model.report(error) } }
    }
}
extension JSONValue {
    var stableID: String { self["id"].string ?? formatted }
    var requestKey: String { self["id"].formatted + ":" + self["fingerprint"].text }
}
struct ConversationTimelineRow: View {
    let item: JSONValue
    let threadID: String
    var body: some View {
        if item["type"].text == "processGroup" {
            ConversationProcessView(item: item, threadID: threadID)
        } else { TimelineEntry(item: item, threadID: threadID) }
    }
}

struct TimelineEntry: View {
    @Environment(AppModel.self) private var model
    @Environment(\.conversationContentContext) private var contentContext
    let item: JSONValue
    let threadID: String
    private var canEdit: Bool {
        !contentContext.isReadOnly && model.canInteract && model.selectedThread?.id == threadID &&
        model.state == "idle" && model.history["syncing"].bool != true &&
        item["type"].text == "userMessage" && item["turnId"] != .null &&
        item["turnId"] == model.history["controls"]["lastTurnId"] &&
        !model.history["controls"]["lastUserText"].text.isEmpty &&
        model.history["timeline"].array.last(where: { $0["type"].text == "userMessage" })?.stableID == item.stableID
    }
    var body: some View {
        let kind = item["type"].text
        if kind == "turn" {
            EmptyView()
        } else if ["userMessage", "steeringUserMessage", "agentMessage"].contains(kind) {
            let user = kind != "agentMessage"
            VStack(alignment: .leading, spacing: 11) {
                let parts = item["data"]["content"].array + item["data"]["input"].array
                let nativePaths = Set(parts.filter { $0["type"].text == "localImage" }.map { $0["path"].text })
                let refs = item["artifacts"].array.filter { !nativePaths.contains($0["path"].text) && (user || $0["kind"].text == "image" || !ConversationPresentation.referencedArtifactIDs(item).contains($0["id"].text)) }
                if user { MessageThumbnails(parts: parts, refs: refs, threadID: threadID, alignTrailing: true) }
                else { ForEach(refs.filter { $0["kind"].text == "image" }, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID, inlineImage: true) } }
                MessageMarkdown(text: user ? (item["displayText"].string ?? item["text"].text) : ConversationPresentation.attachmentDisplayText(item), artifacts: user ? [] : item["artifacts"].array, threadID: threadID, resolveCreatedThreads: !user)
                    .padding(user ? 13 : 0).background(user ? Design.background : .clear, in: RoundedRectangle(cornerRadius: 19))
                    .frame(maxWidth: .infinity, alignment: user ? .trailing : .leading)
                    .onTapGesture(count: 2) { if canEdit { model.beginEditing(item) } }
                    .accessibilityActions { if canEdit { Button("编辑消息") { model.beginEditing(item) } } }
                if !contentContext.isReadOnly { ForEach(item["asyncQuestions"].array, id: \.stableID) { question in AsyncQuestionView(question: question, threadID: threadID) } }
                ForEach(refs.filter { $0["kind"].text != "image" }, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID) }
            }.padding(.leading, user ? 32 : 0)

        } else if !item["subagents"].array.isEmpty {
            AgentActivityGroup(items: [item], parentID: threadID)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                if ConversationPresentation.hasActivityDetails(item) { ExecutionActivityRow(item: item, threadID: threadID) }
                else { ActivityLabel(item: item) }
                ForEach(item["artifacts"].array, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID, inlineImage: true) }
            }
        }
    }
}
private struct ActivityLabel: View {
    let item: JSONValue
    var interactive = false
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: item["type"].text == "reasoning" ? "sparkles" : item["type"].text == "fileChange" ? "doc.text" : "terminal")
            Text(ConversationPresentation.activityLabel(item, text: ConversationProcess.activitySummary(item)))
                .lineLimit(1).truncationMode(.tail)
        }.font(.system(size: 12)).foregroundStyle(interactive ? Design.link : Design.secondary)
    }
}

struct MessageImage: View {
    @Environment(AppModel.self) private var model
    @Environment(\.conversationContentContext) private var contentContext
    let part: JSONValue
    let threadID: String
    @State private var image: UIImage?
    @State private var failure: String?
    var body: some View {
        Group {
            if let image { Button { model.previewImage = image } label: { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 88).clipped() }.buttonStyle(.plain).accessibilityLabel("打开原图") }
            else if let failure { Button { self.failure = nil } label: { Label("重试", systemImage: "arrow.clockwise").font(.caption) }.accessibilityHint(failure) }
            else { ProgressView().task { await load() } }
        }.frame(width: 88, height: 88).clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.black.opacity(0.12)))
    }
    private func load() async {
        do {
            var url = part["url"].text
            if part["type"].text == "localImage" {
                let result = try await model.deviceRequest(contentContext.resourcePath(threadID: threadID, kind: "images", id: part["imageId"].text))
                url = result["url"].text
            }
            let source = url
            let decoded = try await Task.detached(priority: .userInitiated) {
                try autoreleasepool {
                    guard source.hasPrefix("data:image/"), source.utf8.count < 12_000_000, let comma = source.firstIndex(of: ","),
                          let data = Data(base64Encoded: String(source[source.index(after: comma)...])), let image = UIImage(data: data) else { throw APIError("图片格式不受支持") }
                    return image.preparingForDisplay() ?? image
                }
            }.value
            try Task.checkCancellation()
            image = decoded
        } catch is CancellationError { return }
        catch { failure = error.localizedDescription }
    }
}
struct EditMessageView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let item: JSONValue
    let threadID: String
    let scope: String
    @State private var sending = false
    @State private var failed = false
    @FocusState private var focused: Bool
    private var canSend: Bool {
        !sending && model.canInteract && !model.conversationReadOnly && model.scope == scope &&
        model.selectedThread?.id == threadID && model.editingMessage == item && model.state == "idle" &&
        model.history["syncing"].bool != true && item["turnId"] == model.history["controls"]["lastTurnId"] &&
        !model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
    var body: some View {
        @Bindable var model = model
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                TextEditor(text: $model.draft).focused($focused)
                    .padding(8).background(Design.background, in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityLabel("修改消息内容").disabled(sending)
                let parts = item["data"]["content"].array + item["data"]["input"].array
                let paths = Set(parts.filter { $0["type"].text == "localImage" }.map { $0["path"].text })
                MessageThumbnails(parts: parts, refs: item["artifacts"].array.filter { !paths.contains($0["path"].text) }, threadID: threadID)
                ForEach(item["artifacts"].array.filter { $0["kind"].text != "image" }, id: \.stableID) { ref in
                    ArtifactView(ref: ref, threadID: threadID)
                }
                if failed { Text("发送失败，请重试").font(.caption).foregroundStyle(.red) }
            }.padding(20)
                .navigationTitle("编辑消息").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("取消") { model.cancelEditing(); dismiss() }.disabled(sending)
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("发送") {
                            guard canSend else { return }
                            sending = true; failed = false
                            Task {
                                let success = await model.compose()
                                sending = false
                                if success { dismiss() } else { failed = true }
                            }
                        }.disabled(!canSend)
                    }
                }
        }.interactiveDismissDisabled(sending)
            .onAppear { focused = true }
    }
}

struct ModelInformationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ConversationActionTarget
    private var snapshot: JSONValue { model.snapshot(for: target) }
    @State private var choices: [JSONValue] = []
    @State private var selectedModel = ""
    @State private var effort = ""
    @State private var loading = true
    @State private var saving = false
    @State private var failure: String?
    private var efforts: [String] { choices.first { $0["id"].text == selectedModel }?["efforts"].array.compactMap(\.string) ?? [] }
    var body: some View {
        NavigationStack {
            Form {
                if loading { ProgressView() }
                Picker("模型", selection: $selectedModel) {
                    if !choices.contains(where: { $0["id"].text == selectedModel }) { Text(selectedModel.isEmpty ? "未提供" : selectedModel).tag(selectedModel) }
                    ForEach(choices, id: \.stableID) { Text($0["name"].text).tag($0["id"].text) }
                }.pickerStyle(.menu).disabled(choices.isEmpty || saving || !model.canPerform(target))
                Picker("思考强度", selection: $effort) {
                    if !efforts.contains(effort) { Text(effort.isEmpty ? "未提供" : effort).tag(effort) }
                    ForEach(efforts, id: \.self) { Text($0).tag($0) }
                }.pickerStyle(.menu).disabled(efforts.isEmpty || saving || !model.canPerform(target))
                if let failure { Text(failure).foregroundStyle(.red) }
                if !loading && choices.isEmpty { Text("暂未读取到本机模型目录").foregroundStyle(Design.secondary) }
                Text("从下一轮生效").font(.caption).foregroundStyle(Design.secondary)
            }.navigationTitle("模型与思考强度").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("保存") { Task {
                            saving = true
                            if await model.perform("settings", target: target, fields: ["settings": .object(["model": .string(selectedModel), "effort": .string(effort)])]) { dismiss() }
                            saving = false
                        } }.disabled(saving || loading || !model.canPerform(target) || !efforts.contains(effort))
                    }
                }
                .task {
                    selectedModel = snapshot["controls"]["settings"]["model"].string ?? snapshot["metadata"]["latestModel"].text
                    effort = snapshot["controls"]["settings"]["effort"].string ?? snapshot["metadata"]["latestReasoningEffort"].text
                    do { choices = try await model.deviceRequest("/api/models")["models"].array }
                    catch { failure = error.localizedDescription }
                    loading = false
                }
                .onChange(of: selectedModel) { _, value in
                    if !efforts.isEmpty && !efforts.contains(effort) {
                        effort = choices.first { $0["id"].text == value }?["defaultEffort"].string ?? efforts[0]
                    }
                }
        }.presentationDetents([.medium])
    }
}

struct ArtifactView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.conversationContentContext) private var contentContext
    let ref: JSONValue
    let threadID: String
    var openOnLoad = false
    var inlineImage = false
    @State private var image: UIImage?
    @State private var preview: URL?
    @State private var codeDocument: CodeDocument?
    @State private var localFile: URL?
    @State private var failure: String?
    @State private var loading = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !openOnLoad, ref["kind"].text != "image" { Button(ref["name"].text) { Task { await openFile() } }
                .font(.caption).bold().foregroundStyle(Design.link).disabled(loading).accessibilityHint("预览文件") }
            if !openOnLoad, let image {
                Button { model.previewImage = image } label: {
                    if inlineImage {
                        let scale = min(1, min(160 / max(image.size.width, 1), 180 / max(image.size.height, 1)))
                        Image(uiImage: image).resizable().scaledToFit()
                            .frame(width: image.size.width * scale, height: image.size.height * scale)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    else { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 88).clipped().clipShape(RoundedRectangle(cornerRadius: 12)) }
                }.buttonStyle(.plain).accessibilityLabel("打开原图")
            }
            if loading { ProgressView() }
            if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
            HStack {
                if ref["kind"].text != "image", let localFile { ShareLink(item: localFile) { Label("分享文件", systemImage: "square.and.arrow.up") } }
            }.font(.caption)
        }
        .frame(width: ref["kind"].text == "image" && !inlineImage ? 88 : nil, height: ref["kind"].text == "image" && !inlineImage ? 88 : nil)
        .frame(maxWidth: inlineImage ? .infinity : nil, alignment: .leading)
        .task(id: ref.stableID) {
            if openOnLoad {
                if ref["kind"].text == "image" {
                    await load()
                    if image != nil { model.previewImage = image } else if let localFile { preview = localFile }
                }
                else { await openFile() }
            } else if ref["kind"].text == "image" { await load() }
        }
        .quickLookPreview($preview)
        .sheet(item: $codeDocument) { CodeFilePreview(document: $0) }

        .onDisappear { if let localFile { try? FileManager.default.removeItem(at: localFile.deletingLastPathComponent()) }; localFile = nil }
    }
    private func openFile() async {
        await load()
        guard let localFile else { return }
        do {
            let data = try Data(contentsOf: localFile)
            if let document = CodeDocument(name: localFile.lastPathComponent, data: data) { codeDocument = document }
            else { preview = localFile }
        } catch { failure = error.localizedDescription }
    }
    private func load() async {
        guard localFile == nil, !loading else { return }
        loading = true; defer { loading = false }
        do {
            let encoded: String, name: String
            if let url = ref["url"].string, url.hasPrefix("data:image/"), let comma = url.firstIndex(of: ",") {
                encoded = String(url[url.index(after: comma)...])
                let mime = String(url.prefix(while: { $0 != ";" })).replacingOccurrences(of: "data:image/", with: "")
                name = "image." + (["png", "jpeg", "gif", "webp"].contains(mime) ? mime : "png")
            } else {
                let result = try await model.deviceRequest(contentContext.resourcePath(threadID: threadID, kind: "artifacts", id: ref["id"].text))
                encoded = result["base64"].text
                let basename = (ref["name"].text as NSString).lastPathComponent
                name = basename.isEmpty || basename == "." || basename == ".." ? "attachment" : basename
            }
            try Task.checkCancellation()
            let loaded = try await Task.detached(priority: .userInitiated) {
                try autoreleasepool {
                    guard let data = Data(base64Encoded: encoded), data.count <= 8 * 1024 * 1024 else { throw APIError("附件内容无效") }
                    let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
                    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                    do {
                        let file = folder.appendingPathComponent(name)
                        try data.write(to: file, options: .atomic)
                        let decoded = UIImage(data: data)
                        return (file, decoded?.preparingForDisplay() ?? decoded)
                    } catch {
                        try? FileManager.default.removeItem(at: folder)
                        throw error
                    }
                }
            }.value
            guard !Task.isCancelled else {
                try? FileManager.default.removeItem(at: loaded.0.deletingLastPathComponent())
                return
            }
            localFile = loaded.0; image = loaded.1; failure = nil
        } catch is CancellationError {
            return
        } catch {
            failure = error.localizedDescription
            if openOnLoad { model.report(error, operation: "预览附件") }
        }
    }
}

struct AsyncQuestionView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.conversationContentContext) private var context
    let question: JSONValue
    let threadID: String
    private var target: ConversationActionTarget { .init(scope: model.scope, threadID: threadID, parentID: context.parentID) }
    @State private var expanded = false
    @State private var initialized = false
    @State private var touched = false
    @State private var selected = ""
    @State private var custom = ""
    @State private var useCustom = false
    @State private var submitting = false
    @State private var submitted = false
    @State private var lastSubmission: String?
    private var answer: String { (useCustom ? custom : selected).trimmingCharacters(in: .whitespacesAndNewlines) }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if expanded {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Label("问题", systemImage: "questionmark.bubble").font(.caption).foregroundStyle(Design.secondary)
                        Spacer()
                        Button { touched = true; expanded = false } label: { Image(systemName: "xmark") }.accessibilityLabel("收起问题")
                    }
                    Text(question["title"].text).font(.system(size: 14)).fixedSize(horizontal: false, vertical: true)
                    ForEach(Array(question["options"].array.enumerated()), id: \.offset) { index, option in
                        Button { touched = true; selected = option.text; useCustom = false } label: {
                            HStack(spacing: 10) {
                                Text("\(index + 1)").font(.caption).frame(width: 28, height: 28)
                                    .background(!useCustom && selected == option.text ? Design.ink : Color.black.opacity(0.05), in: Circle())
                                    .foregroundStyle(!useCustom && selected == option.text ? .white : Design.secondary)
                                Text(option.text).font(.system(size: 14)).multilineTextAlignment(.leading)
                                Spacer(minLength: 0)
                            }.frame(minHeight: 40).contentShape(Rectangle())
                        }.buttonStyle(.plain).accessibilityAddTraits(!useCustom && selected == option.text ? .isSelected : [])
                    }
                    TextField("或输入你的回答", text: $custom, axis: .vertical).font(.system(size: 14)).lineLimit(1...4)
                        .onTapGesture { touched = true; useCustom = true }
                        .onChange(of: custom) { _, _ in touched = true; useCustom = true }
                    HStack {
                        Spacer()
                        Button("跳过") { touched = true; expanded = false }
                        Button("发送") { Task { await send() } }.buttonStyle(.borderedProminent)
                            .disabled(answer.isEmpty || answer == lastSubmission || !model.canPerform(target) || submitting)
                    }.font(.caption)
                }.padding(16).background(Design.background, in: RoundedRectangle(cornerRadius: 18)).disabled(submitting)
            } else {
                Button { touched = true; expanded = true } label: {
                    Label(question["answer"] != .null ? "回答已同步" : submitted ? "回答已发送，等待同步" : "回答问题", systemImage: "questionmark.bubble")
                        .font(.caption).padding(.horizontal, 12).padding(.vertical, 8)
                        .overlay(Capsule().stroke(Color.black.opacity(0.12)))
                }.buttonStyle(.plain)
            }
        }
        .task(id: question.stableID) {
            if !initialized {
                initialized = true; selected = question["answer"].string ?? question["options"].array.first?.text ?? ""
                lastSubmission = question["answer"].string
                if let previous = lastSubmission, !question["options"].array.contains(.string(previous)) { custom = previous; useCustom = true }
                expanded = question["active"].bool == true && question["answer"] == .null
            }
            do { try await Task.sleep(for: .seconds(30)); if !touched { expanded = false } } catch {}
        }
        .onChange(of: question["answer"]) { _, value in if value != .null { submitted = true; lastSubmission = value.string; expanded = false } }
        .onChange(of: question["active"]) { _, value in if value.bool != true && !touched { expanded = false } }
    }
    private func send() async {
        guard !submitting, !answer.isEmpty, answer != lastSubmission, model.canPerform(target) else { return }
        touched = true; submitting = true; defer { submitting = false }
        let sent = answer
        if await model.answer(question, text: sent, target: target) { submitted = true; lastSubmission = sent; expanded = false }
    }
}

private struct MessageThumbnails: View {
    let parts: [JSONValue]
    let refs: [JSONValue]
    let threadID: String
    var alignTrailing = false
    var body: some View {
        let images = parts.filter { ["image", "localImage"].contains($0["type"].text) }
        let artifacts = refs.filter { $0["kind"].text == "image" }
        if !images.isEmpty || !artifacts.isEmpty {
            GeometryReader { geometry in
              ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Array(images.enumerated()), id: \.offset) { _, part in MessageImage(part: part, threadID: threadID) }
                    ForEach(artifacts, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID) }
                }.frame(minWidth: geometry.size.width, alignment: alignTrailing ? .trailing : .leading)
              }
            }.frame(height: 88)
        }
    }
}

enum CarryOnMessageAction: MessageMenuAction {
    case copy
    func title() -> String { "复制原文" }
    func icon() -> Image { Image(systemName: "doc.on.doc") }
    static func menuItems(for message: ExyteChat.Message) -> [Self] {
        guard let item = message.customData["entry"] as? JSONValue,
              ["userMessage", "steeringUserMessage", "agentMessage"].contains(item["type"].text) else { return [] }
        return [.copy]
    }
}
