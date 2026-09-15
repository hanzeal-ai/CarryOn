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
    private var timeline: [JSONValue] { groupedTimeline(model.history["timeline"].array) }
    @State private var chatMessages: [ExyteChat.Message] = []
    @State private var tableUpdates: TableUpdateTransaction?
    @State private var disclosureState = ConversationDisclosureState()
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
        } + [ExyteChat.Message(id: "carryon:status", user: .init(id: "status", name: "", avatarURL: nil, type: .system),
                             createdAt: Date(timeIntervalSince1970: Double(rows.count)),
                             text: supplemental.formatted, customData: ["supplemental": supplemental])]
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
        .showDateHeaders(false)
        .showAvatar(false)
        .showMessageMenuOnLongPress(false)
        .showScrollToBottomButton(true)
        .keyboardDismissMode(.interactive)
        .mainHeaderBuilder { historyHeader }
        .betweenListAndInputViewBuilder { composerAccessories }
        .onContentOffsetChange { offset in
            bottomVisible = offset <= 20
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
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(model.connectionLabel + executionDuration(model.history["timeline"].array, earlier: model.history["earlierDurationMs"].int ?? 0, now: context.date))
                    .font(.caption2).foregroundStyle(Design.secondary).padding(5)
            }
        }
        .sheet(isPresented: $menu) { ConversationMenu() }
        .sheet(isPresented: $modelInfo) { ModelInformationView() }
        .sheet(isPresented: Binding(get: { model.editingMessage != .null }, set: { if !$0 { model.cancelEditing() } })) {
            EditMessageView(item: model.editingMessage, threadID: thread.id, scope: model.scope)
        }
        .onChange(of: model.historyRevision, initial: true) { _, _ in
            refreshMessages()
            if bottomVisible { markRead() }
        }
        .onChange(of: visibleCount) { _, _ in refreshMessages() }
        .onChange(of: model.visibleOutgoing) { _, _ in refreshMessages() }
        .onChange(of: model.historyFailure) { _, _ in refreshMessages() }
        .onChange(of: model.conversationReadOnly) { _, _ in refreshMessages() }
        .onChange(of: photos) { _, selection in Task { await loadPhotos(selection) } }
        .onDisappear { selectionGeneration = UUID(); loadingImages = false }
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
            if model.history["historyWindow"]["hasMore"].bool == true {
                Button("加载更早记录") {
                    visibleCount += 120; model.loadEarlierHistory()
                }.font(.caption).frame(minHeight: 44).disabled(!model.connected)
            }
            if model.historyFailure == nil && model.history["syncing"].bool == true && !timeline.isEmpty {
                Text("已显示本地记录，正在同步原生历史").font(.caption).foregroundStyle(Design.secondary)
            }
            if timeline.count > visibleCount { Button("显示更早记录（还有 \(timeline.count - visibleCount) 条）") { visibleCount += 120 }.font(.caption).frame(minHeight: 44) }

        }.padding(.horizontal, 16)
    }
    private func supplementalRows(_ snapshot: JSONValue) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if snapshot["showEmpty"].bool == true && snapshot["outgoing"].array.isEmpty {
                BlankState(
                    text: snapshot["syncing"].bool == true ? "正在同步会话…" : "暂无会话记录", loading: snapshot["syncing"].bool == true, symbol: "bubble.left.and.bubble.right")
            }
            ForEach(snapshot["readOnly"].bool == true ? [] : snapshot["requests"].array, id: \.requestKey) { request in
                NativeRequestView(request: request).id(request.requestKey)
            }
            let unsupported = snapshot["pendingRequests"].array.count - snapshot["requests"].array.count
            if unsupported > 0 { Text("另有 \(unsupported) 项请求尚未适配，请在 Codex App 处理。").font(.caption).foregroundStyle(Design.secondary) }
            if !snapshot["queue"]["messages"].array.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("等待队列").font(.caption).fontWeight(.semibold)
                    ForEach(snapshot["queue"]["messages"].array, id: \.stableID) { Text($0["text"].text).font(.caption).textSelection(.enabled) }
                }.padding(13).frame(maxWidth: .infinity, alignment: .leading).background(Design.background, in: RoundedRectangle(cornerRadius: 12))
            }
            ForEach(snapshot["outgoing"].array, id: \.stableID) { item in
                OutgoingMessageStatusView(item: item) { model.outgoing.removeValue(forKey: item["id"].text) }
            }


        }
    }
    private var composerAccessories: some View {
        VStack(alignment: .leading, spacing: 8) {
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
    private func send() async {
        guard !submitting, model.canInteract, !loadingImages else { return }
        submitting = true; defer { submitting = false }
        if await model.compose(images: images.map(JSONValue.string)) { photos = [] }
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
            var result: [String] = []
            for photo in selection {
                guard let data = try await photo.loadTransferable(type: Data.self), let image = UIImage(data: data) else { throw APIError("图片无法读取") }
                let scale = min(1, 1280 / max(image.size.width, image.size.height))
                let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
                let format = UIGraphicsImageRendererFormat(); format.scale = 1
                let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
                var encoded: Data?
                for quality in [0.75, 0.5, 0.3, 0.15] { if let bytes = resized.jpegData(compressionQuality: quality), bytes.count <= 200 * 1024 { encoded = bytes; break } }
                guard let encoded else { throw APIError("图片压缩后仍超过 200 KB，请选择更小的图片") }
                result.append("data:image/jpeg;base64," + encoded.base64EncodedString())
            }
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
        if item["type"].text == "activityGroup" {
            if item["items"].array.count == 1, let child = item["items"].array.first,
               !ConversationPresentation.hasActivityDetails(child) {
                ActivityLabel(item: child)
            } else { ConversationDisclosureGroup(key: threadID + "\n" + item.stableID) {
                ForEach(item["items"].array, id: \.stableID) { child in TimelineEntry(item: child, threadID: threadID) }
            } label: { ActivityLabel(item: item["items"].array.last(where: { $0["status"].text == "inProgress" }) ?? item["items"].array.last ?? .null, interactive: true) }
                .font(.caption).tint(Design.secondary).disclosureGroupStyle(CompactActivityStyle())
            }
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
            VStack(spacing: 3) {
                Text(item["title"].text + " · " + item["status"].text)
                if case .number(let completed) = item["data"]["completedAt"] {
                    Text("完成于 " + Date(timeIntervalSince1970: completed).formatted(date: .abbreviated, time: .standard))
                }
            }.font(.system(size: 10)).foregroundStyle(Design.secondary).frame(maxWidth: .infinity).padding(.vertical, 3)
        } else if ["userMessage", "steeringUserMessage", "agentMessage"].contains(kind) {
            let user = kind != "agentMessage"
            VStack(alignment: .leading, spacing: 11) {
                let parts = item["data"]["content"].array + item["data"]["input"].array
                let nativePaths = Set(parts.filter { $0["type"].text == "localImage" }.map { $0["path"].text })
                let refs = item["artifacts"].array.filter { !nativePaths.contains($0["path"].text) && (user || !ConversationPresentation.referencedArtifactIDs(item).contains($0["id"].text)) }
                MessageThumbnails(parts: parts, refs: refs, threadID: threadID, alignTrailing: user)
                MessageMarkdown(text: user ? (item["displayText"].string ?? item["text"].text) : ConversationPresentation.attachmentDisplayText(item), artifacts: user ? [] : item["artifacts"].array, threadID: threadID, resolveCreatedThreads: !user)
                    .padding(user ? 13 : 0).background(user ? Design.background : .clear, in: RoundedRectangle(cornerRadius: 19))
                    .frame(maxWidth: .infinity, alignment: user ? .trailing : .leading)
                    .onTapGesture(count: 2) { if canEdit { model.beginEditing(item) } }
                    .accessibilityActions { if canEdit { Button("编辑消息") { model.beginEditing(item) } } }
                if !contentContext.isReadOnly { ForEach(item["asyncQuestions"].array, id: \.stableID) { question in AsyncQuestionView(question: question, threadID: threadID) } }
                ForEach(refs.filter { $0["kind"].text != "image" }, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID) }
            }.padding(.leading, user ? 32 : 0)

        } else if !item["subagents"].array.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SubagentLinks(item: item, parentID: threadID)
                if kind == "collabAgentToolCall" {
                    ConversationDisclosureGroup(key: threadID + "\n" + item.stableID) {
                        Text(item["data"].formatted).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    } label: { Text("协作详情") }
                    .font(.caption).tint(Design.secondary).disclosureGroupStyle(CompactActivityStyle())
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
        } else if !item["artifacts"].array.isEmpty {
            MessageThumbnails(parts: [], refs: item["artifacts"].array, threadID: threadID)
            ForEach(item["artifacts"].array.filter { $0["kind"].text != "image" }, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID) }
        } else if !ConversationPresentation.hasActivityDetails(item) {
            ActivityLabel(item: item)
        } else {
            ConversationDisclosureGroup(key: threadID + "\n" + item.stableID) {
                if !(item["data"].object ?? [:]).isEmpty { Text(item["data"].formatted).font(.system(size: 11, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 2) }
                if item["supported"].bool == false { Text("此类型尚未适配，请在 Codex App 查看完整内容。").font(.caption) }
            } label: {
                ActivityLabel(item: item, interactive: true)
            }.tint(Design.secondary).disclosureGroupStyle(CompactActivityStyle())
        }
    }
}
private struct ActivityLabel: View {
    let item: JSONValue
    var interactive = false
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: item["type"].text == "reasoning" ? "sparkles" : item["type"].text == "fileChange" ? "doc.text" : "terminal")
            Text(ConversationPresentation.activityLabel(item))
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
    @State private var showImage = false
    var body: some View {
        Group {
            if let image { Button { showImage = true } label: { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 88).clipped() }.buttonStyle(.plain).accessibilityLabel("打开原图") }
            else if let failure { Button { self.failure = nil } label: { Label("重试", systemImage: "arrow.clockwise").font(.caption) }.accessibilityHint(failure) }
            else { ProgressView().task { await load() } }
        }.frame(width: 88, height: 88).clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.black.opacity(0.12)))
            .background(ImageLightboxPresenter(image: image, isPresented: $showImage).frame(width: 0, height: 0))

    }
    private func load() async {
        do {
            var url = part["url"].text
            if part["type"].text == "localImage" {
                let result = try await model.deviceRequest(contentContext.resourcePath(threadID: threadID, kind: "images", id: part["imageId"].text))
                url = result["url"].text
            }
            guard url.hasPrefix("data:image/"), url.utf8.count < 12_000_000, let comma = url.firstIndex(of: ","),
                  let data = Data(base64Encoded: String(url[url.index(after: comma)...])), let decoded = UIImage(data: data) else { throw APIError("图片格式不受支持") }
            try Task.checkCancellation()
            image = decoded
        } catch { failure = error.localizedDescription }
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
                }.pickerStyle(.menu).disabled(choices.isEmpty || saving || !model.canInteract)
                Picker("思考强度", selection: $effort) {
                    if !efforts.contains(effort) { Text(effort.isEmpty ? "未提供" : effort).tag(effort) }
                    ForEach(efforts, id: \.self) { Text($0).tag($0) }
                }.pickerStyle(.menu).disabled(efforts.isEmpty || saving || !model.canInteract)
                if let failure { Text(failure).foregroundStyle(.red) }
                if !loading && choices.isEmpty { Text("暂未读取到本机模型目录").foregroundStyle(Design.secondary) }
                Text("从下一轮生效").font(.caption).foregroundStyle(Design.secondary)
            }.navigationTitle("模型与思考强度").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("保存") { Task {
                            saving = true
                            if await model.operation("settings", fields: ["settings": .object(["model": .string(selectedModel), "effort": .string(effort)])]) { dismiss() }
                            saving = false
                        } }.disabled(saving || loading || !model.canInteract || !efforts.contains(effort))
                    }
                }
                .task {
                    selectedModel = model.history["controls"]["settings"]["model"].string ?? model.history["metadata"]["latestModel"].text
                    effort = model.history["controls"]["settings"]["effort"].string ?? model.history["metadata"]["latestReasoningEffort"].text
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

func groupedTimeline(_ items: [JSONValue]) -> [JSONValue] {
    var result: [JSONValue] = [], pending: [JSONValue] = []
    func flush() {
        if let first = pending.first {
            result.append(.object(["id": .string(first.stableID + ":group"), "type": .string("activityGroup"), "items": .array(pending)]))
            pending = []
        }
    }
    for item in ConversationPresentation.visibleReasoning(items) {
        if !["turn", "userMessage", "steeringUserMessage", "agentMessage", "error"].contains(item["type"].text) && item["artifacts"].array.isEmpty && item["subagents"].array.isEmpty { pending.append(item) }
        else { flush(); result.append(item) }
    }
    flush(); return result
}
private func executionDuration(_ items: [JSONValue], earlier: Int = 0, now: Date) -> String {
    var elapsed = Double(earlier)
    for item in items where item["type"].text == "turn" {
        if case .number(let duration) = item["data"]["durationMs"] { elapsed += duration }
        else if item["status"].text == "inProgress", case .number(let start) = item["data"]["turnStartedAtMs"] { elapsed += max(0, now.timeIntervalSince1970 * 1000 - start) }
    }
    guard elapsed > 0 else { return "" }
    let seconds = Int(elapsed / 1000)
    return " · 已执行 \(seconds / 60)分\(seconds % 60)秒"
}

struct ArtifactView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.conversationContentContext) private var contentContext
    let ref: JSONValue
    let threadID: String
    var openOnLoad = false
    @State private var image: UIImage?
    @State private var preview: URL?
    @State private var codeDocument: CodeDocument?
    @State private var showImage = false
    @State private var localFile: URL?
    @State private var failure: String?
    @State private var loading = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !openOnLoad, ref["kind"].text != "image" { Button(ref["name"].text) { Task { await openFile() } }
                .font(.caption).bold().foregroundStyle(Design.link).disabled(loading).accessibilityHint("预览文件") }
            if !openOnLoad, let image { Button { showImage = true } label: { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 88).clipped().clipShape(RoundedRectangle(cornerRadius: 12)) }.buttonStyle(.plain).accessibilityLabel("打开原图") }
            if loading { ProgressView() }
            if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
            HStack {
                if ref["kind"].text != "image", let localFile { ShareLink(item: localFile) { Label("分享文件", systemImage: "square.and.arrow.up") } }
            }.font(.caption)
        }
        .frame(width: ref["kind"].text == "image" ? 88 : nil, height: ref["kind"].text == "image" ? 88 : nil)
        .task(id: ref.stableID) {
            if openOnLoad {
                if ref["kind"].text == "image" {
                    await load()
                    if image != nil { showImage = true } else if let localFile { preview = localFile }
                }
                else { await openFile() }
            } else if ref["kind"].text == "image" { await load() }
        }
        .quickLookPreview($preview)
        .sheet(item: $codeDocument) { CodeFilePreview(document: $0) }
        .background(ImageLightboxPresenter(image: image, isPresented: $showImage).frame(width: 0, height: 0))
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
            if let url = ref["url"].string, url.hasPrefix("data:image/"), let comma = url.firstIndex(of: ","),
               let data = Data(base64Encoded: String(url[url.index(after: comma)...])), data.count <= 8 * 1024 * 1024,
               let decoded = UIImage(data: data) {
                image = decoded
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let mime = String(url.prefix(while: { $0 != ";" })).replacingOccurrences(of: "data:image/", with: "")
                let file = folder.appendingPathComponent("image." + (["png", "jpeg", "gif", "webp"].contains(mime) ? mime : "png"))
                try data.write(to: file, options: .atomic)
                localFile = file
                return
            }
            let result = try await model.deviceRequest(contentContext.resourcePath(threadID: threadID, kind: "artifacts", id: ref["id"].text))
            guard let data = Data(base64Encoded: result["base64"].text), data.count <= 8 * 1024 * 1024 else { throw APIError("附件内容无效") }
            try Task.checkCancellation()
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let name = (ref["name"].text as NSString).lastPathComponent
            let file = folder.appendingPathComponent(name.isEmpty || name == "." || name == ".." ? "attachment" : name)
            try data.write(to: file, options: .atomic)
            localFile = file; image = UIImage(data: data); failure = nil
        } catch {
            failure = error.localizedDescription
            if openOnLoad { model.report(error, operation: "预览附件") }
        }
    }
}

private struct CompactActivityStyle: DisclosureGroupStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { configuration.isExpanded.toggle() } label: {
                HStack(spacing: 6) {
                    configuration.label
                    Image(systemName: "chevron.down").font(.system(size: 9))
                    Spacer(minLength: 0)
                }.contentShape(Rectangle())
            }.buttonStyle(.plain).foregroundStyle(Design.link).accessibilityValue(configuration.isExpanded ? "已展开" : "已收起")
            if configuration.isExpanded { VStack(alignment: .leading, spacing: 0) { configuration.content } }
        }
    }
}

struct AsyncQuestionView: View {
    @Environment(AppModel.self) private var model
    let question: JSONValue
    let threadID: String
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
                            .disabled(answer.isEmpty || answer == lastSubmission || !model.canInteract || submitting)
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
        guard !submitting, !answer.isEmpty, answer != lastSubmission, model.canInteract, model.selectedThread?.id == threadID else { return }
        touched = true; submitting = true; defer { submitting = false }
        let sent = answer
        if await model.answerQuestion(question, answer: sent, threadID: threadID) { submitted = true; lastSubmission = sent; expanded = false }
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

private enum CarryOnMessageAction: MessageMenuAction {
    case copy
    func title() -> String { "复制原文" }
    func icon() -> Image { Image(systemName: "doc.on.doc") }
    static func menuItems(for message: ExyteChat.Message) -> [Self] {
        guard let item = message.customData["entry"] as? JSONValue,
              ["userMessage", "steeringUserMessage", "agentMessage"].contains(item["type"].text) else { return [] }
        return [.copy]
    }
}
