import SwiftUI
import PhotosUI
import QuickLook
import CarryOnCore
import ExyteChat

struct ConversationView: View {
    @Environment(AppModel.self) private var model
    let thread: Record
    private struct CommandPanel: Identifiable {
        let id = UUID()
        let name: String
        let argument: String
        let scope: String
        let sourceDraft: String
    }
    @State private var commandPanel: CommandPanel?
    @State private var menu = false
    @State private var activity = false
    @State private var modelInfo = false
    @State private var showingVoice = false
    @State private var composerConfiguration = false
    @State private var contextInformation = false
    @State private var skillsPicker = false
    @State private var mentionsPicker = false
    private struct FilePanel: Identifiable { let id = UUID(); let scope: String; let threadID: String }
    @State private var filesPicker: FilePanel?
    private struct CommentPanel: Identifiable {
        let id = UUID()
        let target: ConversationActionTarget
    }
    @State private var commentPanel: CommentPanel?
    @State private var newMessages = false
    @State private var lastTimelineItem: JSONValue?
    @State private var selectionText: String?
    private struct SideLaunch: Identifiable {
        let id = UUID()
        let text: String
        let autoSend: Bool
        let sourceDraft: String
        let scope: String
        let parentID: String
    }
    @State private var sideLaunch: SideLaunch?
    @State private var pendingSelectionSide: SideLaunch?
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
    @AppStorage("carryon.queueFollowUps") private var queueFollowUps = true
    private var canQueue: Bool { supportsOperation("queue-add", in: model.history) }
    private var queueFollowUp: Bool { canQueue && (queueFollowUps || model.history["controls"]["canSteer"].bool == false) }
    private var queueUnavailable: Bool { ["running", "waiting"].contains(model.state) && ((queueFollowUp && model.history["queue"]["fingerprint"].string == nil) || (model.history["controls"]["canSteer"].bool == false && !canQueue)) }
    private var composerModel: String {
        model.history["controls"]["settings"]["model"].string ?? model.history["metadata"]["latestModel"].string ?? "模型"
    }
    private var composerEffort: String {
        model.history["controls"]["settings"]["effort"].string ?? model.history["metadata"]["latestReasoningEffort"].text
    }
    private var actionTarget: ConversationActionTarget { .init(scope: model.scope, threadID: thread.id) }
    @State private var timeline: [JSONValue] = []
    @State private var navigationIndex = ConversationPresentation.NavigationIndex([])
    @State private var projectedHistoryRevision = -1
    @State private var chatMessages: [ConversationListEntry] = []
    @State private var tableUpdates: ConversationListTransaction?
    @State private var disclosureState = ConversationDisclosureState()
    @State private var readingState: ConversationReadingState?
    @State private var navigationPreview: JSONValue?
    @State private var navigationRailTracker = ConversationNavigationTracker()
    @GestureState private var navigationDragging = false
    @State private var navigationPinned = false
    @State private var navigationAnchor: String?
    @State private var pendingNavigation: String?
    @State private var navigationRepairs = 0
    @State private var navigationRepairScheduled = false
    @State private var navigationRepairLayout: CGRect?
    @State private var navigationBounds: CGRect = .zero
    @State private var navigationTracker = ConversationNavigationTracker()
    @State private var restoreScroll: ConversationListScroll?
    @State private var messageRefresh = ConversationRefreshQueue()
    @State private var displayGeneration = UUID()
    private func refreshMessages() {
        let scope = model.scope, epoch = model.epoch, generation = displayGeneration
        let isCurrent = {
            model.scope == scope && model.epoch == epoch &&
            model.selectedThread?.id == thread.id && displayGeneration == generation
        }
        messageRefresh.request {
            guard isCurrent() else { return }
            let revision = model.historyRevision
            // Capture history and its pending bubbles together before asynchronous rendering.
            let showEmpty = model.historyFailure == nil && model.history != .null && model.history["timeline"].array.isEmpty
            let supplemental: JSONValue = .object([
                "showEmpty": .bool(showEmpty),
                "syncing": .bool(showEmpty && model.history["syncing"].bool == true),
                "outgoing": .array(model.visibleOutgoing)
            ])
            if projectedHistoryRevision != revision {
                let source = model.history["timeline"].array
                let (grouped, navigation) = await Task.detached(priority: .userInitiated) {
                    let grouped = ConversationChanges.timeline(ConversationProcess.timeline(source), source: source)
                    return (grouped, ConversationPresentation.NavigationIndex(grouped))
                }.value
                guard isCurrent() else { return }
                if !bottomVisible, let lastTimelineItem, grouped.last != lastTimelineItem,
                   grouped.contains(where: { $0.stableID == lastTimelineItem.stableID }) { newMessages = true }
                lastTimelineItem = grouped.last
                timeline = grouped; projectedHistoryRevision = revision
                if model.historyRevision == revision, model.historySynchronized, model.historyFailure == nil,
                   model.history["syncing"].bool != true, model.history["historyWindow"]["hasMore"].bool == false,
                   let position = readingState?.visiblePosition, !grouped.contains(where: { $0.stableID == position.id }) {
                    readingState?.visiblePosition = nil
                    if model.activityScrollTarget == nil, pendingNavigation == nil, !navigationPinned, restoreScroll?.messageID == position.id {
                        readingState?.offset = 0; readingState?.anchorID = nil
                        restoreScroll = grouped.last.map { ConversationListScroll(messageID: $0.stableID, position: .bottom) }
                    }
                }
                navigationIndex = navigation
                if navigationPinned { navigationRepairs = 0; navigationRepairLayout = nil }
            }
            // A target may arrive before its history projection. Expand the current
            // message window after resolving the canonical item or process group.
            if let anchor = pendingNavigation ?? model.activityScrollTarget {
                let resolved = timeline.first { $0.stableID == anchor || $0["items"].array.contains { $0.stableID == anchor } }?.stableID ?? anchor
                pendingNavigation = resolved; navigationAnchor = resolved
                if let index = timeline.firstIndex(where: { $0.stableID == resolved }) {
                    visibleCount = max(visibleCount, timeline.count - index)
                }
            }
            let (next, updateRows) = await projectedMessages(supplemental: supplemental)
            guard isCurrent() else { return }
            guard next != chatMessages else {
                let growing = Set(next.compactMap { message -> String? in
                    guard let old = message.presentation,
                          let entry = message.itemSnapshot, entry["type"].text == "agentMessage",
                          entry["text"].text != old.item["text"].text, entry["text"].text.hasPrefix(old.item["text"].text) else { return nil }
                    return message.id
                })
                let anchor = !navigationPinned && pendingNavigation == nil && model.activityScrollTarget == nil ? navigationTracker.captureReadingAnchor(in: growing) : nil
                updateRows.forEach { $0() }
                if let anchor { navigationTracker.restoreReadingAnchor(anchor, valid: { isCurrent() && !navigationPinned && pendingNavigation == nil && model.activityScrollTarget == nil }) }
                applyNavigation(); return
            }
            if let tableUpdates {
                let previous = Dictionary(chatMessages.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
                let growing = Set(next.compactMap { message -> String? in
                    guard let old = previous[message.id]?.presentation?.item,
                          let entry = message.itemSnapshot,
                          entry["type"].text == "agentMessage", !old["text"].text.isEmpty,
                          entry["text"].text != old["text"].text, entry["text"].text.hasPrefix(old["text"].text) else { return nil }
                    return message.id
                })
                let nextIDs = Set(next.map(\.id)), previousIDs = Set(previous.keys)
                let readingCandidates = nextIDs == previousIDs ? growing : previousIDs.intersection(nextIDs)
                var readingAnchor: ConversationNavigationTracker.ReadingAnchor?
                // Serialize snapshots and capture the reading position at the actual mutation.
                await tableUpdates {
                    if isCurrent() {
                        if !navigationPinned, pendingNavigation == nil, model.activityScrollTarget == nil {
                            readingAnchor = navigationTracker.captureReadingAnchor(in: readingCandidates)
                        }
                        updateRows.forEach { $0() }; chatMessages = next
                    }
                }
                if isCurrent(), !navigationPinned, pendingNavigation == nil, model.activityScrollTarget == nil,
                   let readingAnchor { navigationTracker.restoreReadingAnchor(readingAnchor, valid: { isCurrent() && !navigationPinned && pendingNavigation == nil && model.activityScrollTarget == nil }) }
            } else { updateRows.forEach { $0() }; chatMessages = next }
            if isCurrent() { applyNavigation() }
        }
    }

    private func projectedMessages(supplemental: JSONValue) async -> ([ConversationListEntry], [@MainActor () -> Void]) {
        let previous = Dictionary(chatMessages.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let rows = Array(timeline.suffix(visibleCount))
        var messages: [ConversationListEntry] = []
        var updates: [@MainActor () -> Void] = []
        for item in rows {
            let existingRow = previous[item.stableID]?.presentation
            let prepared: ParsedMessageMarkdown?
            if let existingRow, existingRow.item == item { prepared = existingRow.markdown }
            else { prepared = await MessageMarkdownParser.shared.prepare(item) }
            let canEdit = TimelineEntry.canEdit(item, threadID: thread.id, model: model, readOnly: model.conversationReadOnly)
            if var message = previous[item.stableID], let row = message.presentation {
                updates.append {
                    if row.item != item { row.item = item }
                    if row.markdown?.input != prepared?.input { row.markdown = prepared }
                }
                if message.canAskSide != (askInSideAction != nil) || message.canEdit != canEdit || message.itemSnapshot?["type"].text != item["type"].text {
                    message.canAskSide = askInSideAction != nil; message.canEdit = canEdit; message.configuration = UUID()
                }
                message.itemSnapshot = item; messages.append(message)
            } else {
                messages.append(ConversationListEntry(id: item.stableID, itemSnapshot: item,
                    presentation: TimelineRowPresentation(item: item, markdown: prepared), canAskSide: askInSideAction != nil, canEdit: canEdit))
            }
        }
        guard supplemental["showEmpty"].bool == true || !supplemental["outgoing"].array.isEmpty else { return (messages, updates) }
        let status: ConversationListEntry
        if let existing = previous["carryon:status"], existing.supplemental == supplemental { status = existing }
        else { status = ConversationListEntry(id: "carryon:status", supplemental: supplemental) }
        return (messages + [status], updates)
    }
    private func updateContentOffset(_ offset: CGFloat) {
        let scope = model.scope, generation = displayGeneration
        DispatchQueue.main.async {
            guard model.scope == scope, displayGeneration == generation, model.selectedThread?.id == thread.id else { return }
            let reachedBottom = !bottomVisible && offset <= 20
            bottomVisible = offset <= 20
            readingState?.offset = max(0, offset)
            if !chatMessages.isEmpty {
                if offset <= 20 { readingState?.visiblePosition = nil }
                else if let position = navigationTracker.captureVisiblePosition() { readingState?.visiblePosition = position }
            }
            if navigationTracker.isDragging { navigationPinned = false; restoreScroll = nil; navigationPreview = nil }
            navigationLayoutChanged()
            if bottomVisible && !navigationPinned && pendingNavigation == nil && model.activityScrollTarget == nil { readingState?.anchorID = nil; newMessages = false }
            if reachedBottom { markRead() }
            updateNavigationPosition()
        }
    }
    private func performMessageAction(_ action: CarryOnMessageAction, messageID: String, scope: String, epoch: UUID) {
        guard model.scope == scope, model.epoch == epoch, model.selectedThread?.id == thread.id, model.allows(.view),
              let item = chatMessages.first(where: { $0.id == messageID })?.presentation?.item else { return }
        switch action {
        case .edit:
            if TimelineEntry.canEdit(item, threadID: thread.id, model: model, readOnly: model.conversationReadOnly) { model.beginEditing(item) }
        case .copy: UIPasteboard.general.string = item["text"].text
        case .selectText:
            let user = item["type"].text != "agentMessage"
            let text = user ? (item["displayText"].string ?? item["text"].text) : ConversationPresentation.attachmentDisplayText(item)
            selectionText = MessageTextSelectionView.plainText(text, resolveCreatedThreads: !user)
        }
    }
    private var historyRows: [ConversationListRow] {
        guard model.history == .null || model.historyFailure != nil ||
            (model.history["syncing"].bool == true && !model.history["timeline"].array.isEmpty) else { return [] }
        return [ConversationListRow(id: "carryon:history-header", configuration: AnyHashable([
                model.history == .null ? "empty" : "loaded", model.historyFailure,
                model.device?.value["online"].bool == false ? "offline" : "online",
                model.history["syncing"].bool == true ? "syncing" : nil] as [String?]),
                content: AnyView(ConversationListLiveContent { AnyView(historyHeader.frame(maxWidth: .infinity, alignment: .leading)) }.environment(model)))]
    }
    private var chatContent: some View {
        let scope = model.scope, epoch = model.epoch
        return VStack(spacing: 0) {
            ConversationList(rows: historyRows + chatMessages.map { message in
                    ConversationListRow(id: message.id, configuration: AnyHashable(message.configuration),
                        content: AnyView(ConversationListLiveContent { AnyView(messageRow(message, scope: scope, epoch: epoch)
                            .environment(\.conversationContentContext, ConversationContentContext(isReadOnly: model.conversationReadOnly))) }
                            .environment(model).environment(\.conversationDisclosureState, disclosureState)))
                }, scope: scope + thread.id + epoch.uuidString,
                isCurrent: { model.scope == scope && model.epoch == epoch && model.selectedThread?.id == thread.id },
                mayFollowLatest: { !navigationPinned && pendingNavigation == nil && model.activityScrollTarget == nil },
                onOffset: updateContentOffset, olderBoundaryID: chatMessages.first?.id, canLoadEarlier: canLoadEarlier,
                loadEarlier: loadEarlierMessages, transaction: tableUpdates, scroll: restoreScroll)
            composerAccessories.frame(maxWidth: .infinity)
                .anchorPreference(key: ConversationComposerBounds.self, value: .bounds) { $0 }
            composerView
        }
        .background(Design.canvas)
        .chatTheme(colors: .init(mainBG: Design.canvas, mainTint: Design.ink, inputBG: Design.input,
                               inputText: Design.ink, sendButtonBackground: Design.composerAccent))
        .onAppear { if tableUpdates == nil { tableUpdates = ConversationListTransaction() } }
        .overlayPreferenceValue(ConversationComposerBounds.self) { anchor in
            GeometryReader { geometry in
                if let anchor {
                    latestButton.padding(.trailing, 16)
                        .padding(.bottom, max(0, geometry.size.height - geometry[anchor].minY) + 8)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                }
            }
        }
        .overlay(alignment: .leading) { navigationRail.offset(x: 8) }
        .overlay(alignment: .leading) { navigationPreviewCard }
        .environment(\.conversationDisclosureState, disclosureState)
        .environment(\.conversationContentContext, ConversationContentContext(isReadOnly: model.conversationReadOnly))
    }
    private var conversationPresentation: some View {
        chatContent
        .navigationTitle(model.history["thread"]["title"].string ?? model.selectedThread?.title ?? thread.title).navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(!model.threadParents.isEmpty)
        .toolbar {
            if !model.threadParents.isEmpty || model.otherActivityCount > 0 {
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
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { menu = true } label: { Image(systemName: "ellipsis") }.accessibilityLabel("会话操作")
            }
        }
        .sheet(isPresented: Binding(get: { selectionText != nil }, set: { if !$0 { selectionText = nil } }), onDismiss: {
            if let launch = pendingSelectionSide {
                pendingSelectionSide = nil
                if launch.scope == model.scope, launch.parentID == model.selectedThread?.id, supportsOperation("side-create", in: model.history), model.canWrite(.create) { sideLaunch = launch }
            }
        }) {
            if let selectionText { MessageTextSelectionView(text: selectionText, askInSide: selectionSideAction) }
        }

        .sheet(item: $sideLaunch) { launch in
            if model.scope == launch.scope, model.selectedThread?.id == launch.parentID {
                SideChatsView(initialPrompt: launch.text, sendInitialPrompt: launch.autoSend, onCreated: {
                    if launch.autoSend, model.scope == launch.scope, model.selectedThread?.id == launch.parentID, model.draft == launch.sourceDraft { model.draft = "" }
                })
            }
        }
        .task(id: model.scope + thread.id + String(model.workspaceRevision)) {
            do { try await model.refreshActivityCounts() }
            catch { model.report(error, operation: "刷新其他会话角标", blocking: false) }
        }
        .sheet(isPresented: $menu) { ConversationMenu() }
        .sheet(item: $commandPanel) { panel in
            if model.scope == panel.scope, model.selectedThread?.id == thread.id {
                switch panel.name {
                case "review": ReviewConversationView(target: actionTarget, initialInstructions: panel.argument) {}
                case "fork": ForkConversationView(thread: thread, scope: panel.scope, autoCreate: true) {
                    if model.scope == panel.scope, model.selectedThread?.id == thread.id, model.draft == panel.sourceDraft { model.draft = "" }
                }
                case "goal": ConversationGoalView(target: actionTarget)
                default: StructuredDetail(title: "会话信息", value: .object(["status": model.history["status"], "settings": model.history["controls"]["settings"], "metadata": model.history["metadata"]]))
                }
            }
        }

        .sheet(isPresented: $composerConfiguration) { ModelInformationView(target: actionTarget, configuration: true) }
        .alert("上下文用量", isPresented: $contextInformation) { Button("完成", role: .cancel) {} } message: {
            if let usage = ContextUsage(model.history["metadata"]["latestTokenUsageInfo"]) { Text("最近一轮使用 \(usage.used) / \(usage.capacity) tokens，剩余 \(usage.remaining)。") }
        }
        .sheet(isPresented: $showingVoice) { VoiceConversationView(target: actionTarget) }
        .sheet(isPresented: $modelInfo) { ModelInformationView(target: actionTarget) }
        .sheet(isPresented: $skillsPicker) { SkillsPickerView(target: .conversation(actionTarget)) }
        .sheet(item: $filesPicker) { panel in ProjectFilesPicker(threadID: panel.threadID, scope: panel.scope) }
        .sheet(isPresented: $mentionsPicker) { SkillsPickerView(target: .conversation(actionTarget), mentions: true) }
        .sheet(item: $commentPanel) { ReviewCommentsView(target: $0.target) }
        .sheet(isPresented: Binding(get: { model.editingMessage != .null }, set: { if !$0 { model.cancelEditing() } })) {
            EditMessageView(item: model.editingMessage, threadID: thread.id, scope: model.scope)
        }
    }
    var body: some View {
        conversationPresentation
        .onChange(of: model.historyRevision, initial: true) { _, _ in
            if model.history["thread"]["id"].text == thread.id { readingState?.historyLimit = model.historyLimit }
            refreshMessages()
            if bottomVisible { markRead() }
        }
        .onChange(of: model.activityScrollTarget) { _, anchor in
            if let anchor { navigate(to: anchor) }
        }
        .onChange(of: visibleCount) { _, _ in readingState?.visibleCount = visibleCount; refreshMessages() }
        .onChange(of: model.visibleOutgoing) { _, _ in refreshMessages() }
        .onChange(of: model.historyFailure) { _, _ in refreshMessages() }
        .onChange(of: model.conversationReadOnly) { _, _ in refreshMessages() }
        .onChange(of: supportsOperation("side-create", in: model.history) && model.canWrite(.create)) { _, _ in refreshMessages() }
        .onChange(of: model.canInteract(.edit)) { _, _ in refreshMessages() }
        .onChange(of: photos) { _, selection in Task { await loadPhotos(selection) } }
        .onDisappear { navigationTracker.cancelReadingRestoration(); navigationTracker.onLayout = nil; displayGeneration = UUID(); selectionGeneration = UUID(); loadingImages = false }
        .onAppear {
            navigationTracker.onLayout = { navigationLayoutChanged() }
            let state = model.readingState(for: thread.id)
            readingState = state; disclosureState = state.disclosure; visibleCount = state.visibleCount
            bottomVisible = state.offset <= 20
            if let anchor = model.activityScrollTarget { navigationAnchor = anchor; pendingNavigation = anchor; restoreScroll = ConversationListScroll(messageID: anchor, position: .middle) }
            else if let position = state.visiblePosition { restoreScroll = ConversationListScroll(messageID: position.id, position: .top, offset: position.offset) }
            else if let anchor = state.anchorID { navigationAnchor = anchor; pendingNavigation = anchor; restoreScroll = ConversationListScroll(messageID: anchor, position: .middle) }
            else if state.offset > 20 { restoreScroll = ConversationListScroll(offset: state.offset) }
            refreshMessages()
        }
    }
    private var askInSideAction: (@MainActor @Sendable (String) -> Void)? { sideAction(afterSelectionDismiss: false) }
    private var selectionSideAction: (@MainActor @Sendable (String) -> Void)? { sideAction(afterSelectionDismiss: true) }
    private func sideAction(afterSelectionDismiss: Bool) -> (@MainActor @Sendable (String) -> Void)? {
        guard supportsOperation("side-create", in: model.history), model.canWrite(.create) else { return nil }
        let scope = model.scope, target = thread.id
        return { text in
            guard model.scope == scope, model.selectedThread?.id == target,
                  supportsOperation("side-create", in: model.history), model.canWrite(.create) else { return }
            let launch = SideLaunch(text: text, autoSend: false, sourceDraft: model.draft, scope: scope, parentID: target)
            if afterSelectionDismiss { pendingSelectionSide = launch; selectionText = nil }
            else { sideLaunch = launch }
        }
    }
    private func messageRow(_ message: ConversationListEntry, scope: String, epoch: UUID) -> some View {
        let isProcess = message.presentation?.item["type"].text == "processGroup"
        return Group {
            if let item = message.presentation?.item {
                Group {
                    if item["type"].text == "changesSummary" {
                        ConversationChangesCard(history: item["history"], projection: .init(item["history"]), threadID: thread.id)
                    } else {
                        ConversationTimelineRow(item: item, threadID: thread.id)
                    }
                }
                    .environment(\.askInSideChat, askInSideAction)
                    .environment(\.conversationSelectionChanged, { navigationTracker.selectionChanged($0) })
                    .environment(\.preparedMessageMarkdown, message.presentation?.markdown)
            } else if let snapshot = message.supplemental {
                supplementalRows(snapshot)
            }
        }.modifier(ConversationListOptionalMenu(enabled: !message.canAskSide && !message.canEdit,
                actions: CarryOnMessageAction.menuItems(forType: message.presentation?.item["type"].text ?? "", canEdit: message.canEdit).map { action in
                    (action.title(), { performMessageAction(action, messageID: message.id, scope: scope, epoch: epoch) })
                }))
            .padding(.horizontal, 16).padding(.vertical, isProcess ? 2 : 8).frame(maxWidth: .infinity, alignment: .leading)
            .background(ConversationNavigationMarker(id: message.id, tracker: navigationTracker))
    }
    private func navigate(to anchor: String) {
        navigationTracker.cancelReadingRestoration()
        let resolved = timeline.first { $0.stableID == anchor || $0["items"].array.contains { $0.stableID == anchor } }?.stableID ?? anchor
        pendingNavigation = resolved
        navigationAnchor = resolved
        readingState?.anchorID = resolved
        if let index = timeline.firstIndex(where: { $0.stableID == resolved }), timeline.count - index > visibleCount {
            visibleCount = timeline.count - index
        } else { applyNavigation() }
    }
    private func applyNavigation() {
        guard let anchor = pendingNavigation ?? model.activityScrollTarget,
              chatMessages.contains(where: { $0.id == anchor }) else { return }
        navigationAnchor = anchor
        navigationPinned = true
        navigationRepairs = 0
        navigationRepairLayout = nil
        restoreScroll = ConversationListScroll(messageID: anchor, position: .middle)
        pendingNavigation = nil
        model.activityScrollTarget = nil
    }
    private func repairNavigationAfterLayout() {
        guard navigationPinned, !navigationRepairScheduled, navigationRepairs < 3,
              navigationBounds.width > 0, navigationBounds.height > 0,
              let anchor = navigationAnchor, chatMessages.contains(where: { $0.id == anchor }) else { return }
        let scope = model.scope, generation = displayGeneration
        navigationRepairScheduled = true
        // Coalesce all offset callbacks from the same transaction before measuring.
        DispatchQueue.main.async {
            navigationRepairScheduled = false
            guard model.scope == scope, displayGeneration == generation, model.selectedThread?.id == thread.id,
                  navigationPinned, navigationAnchor == anchor, !navigationTracker.isDragging,
                  let layout = navigationTracker.measuredLayout, layout != navigationRepairLayout,
                  !(navigationTracker.frames[anchor]?.intersects(navigationBounds) ?? false) else { return }
            navigationRepairLayout = layout; navigationRepairs += 1
            // The subpixel offset changes the public Equatable scroll request after
            // self-sizing layout; it does not define the reading position.
            restoreScroll = ConversationListScroll(messageID: anchor, position: .middle, offset: CGFloat(navigationRepairs) / 100)
        }
    }
    private func navigationLayoutChanged() {
        if let viewport = navigationTracker.viewportBounds, viewport != navigationBounds { navigationBounds = viewport }
        repairNavigationAfterLayout()
    }
    private func updateNavigationPosition() {
        guard !navigationPinned, pendingNavigation == nil, model.activityScrollTarget == nil, navigationBounds.height > 0 else { return }
        let center = navigationBounds.midY
        let navigationFrames = navigationTracker.frames
        if let nearest = navigationFrames.filter({ $0.value.intersects(navigationBounds) }).min(by: {
            abs($0.value.midY - center) < abs($1.value.midY - center)
        }) { navigationAnchor = nearest.key }
    }
    private var navigationItems: [JSONValue] { navigationIndex.messages }
    private var navigationSelection: String? {
        navigationAnchor.flatMap { navigationIndex.selectionByID[$0] }
    }
    private func navigationText(_ item: JSONValue) -> String {
        let text = item["displayText"].string ?? item["text"].text
        return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "图片消息" : text
    }
    private func navigationButton(_ item: JSONValue, index: Int, center: Int) -> some View {
        let selected = (navigationPreview?.stableID ?? navigationSelection) == item.stableID
        let widths: [CGFloat] = [28, 22, 16, 10, 6]
        let width = widths[min(4, abs(index - center))]
        let label = String(navigationText(item).prefix(60))
        return Button {
            navigationPreview = nil
            navigate(to: item.stableID)
        } label: {
            Rectangle().fill(selected ? Design.ink : Color.secondary.opacity(0.35))
                .frame(width: width, height: 2)
                .frame(width: 32, height: 10, alignment: .leading).contentShape(Rectangle())
        }.buttonStyle(.plain).id(item.stableID)
            .accessibilityLabel("跳转到第 \(index + 1) 条：" + label)
            .accessibilityAddTraits(selected ? .isSelected : [])

    }
    @ViewBuilder private var navigationPreviewCard: some View {
        if let item = navigationPreview {
            VStack(alignment: .leading, spacing: 8) {
                Text(String(navigationText(item).prefix(500)))
                    .font(.subheadline).foregroundStyle(Design.ink).lineLimit(5)
            }.padding(14).frame(width: min(300, max(180, navigationBounds.width - 52)), alignment: .leading)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.secondary.opacity(0.2)))
                .shadow(color: .black.opacity(0.08), radius: 10, y: 4).offset(x: 40).allowsHitTesting(false)
        }
    }
    private var navigationContentOrigin: CGFloat? {
        let frames = navigationRailTracker.frames
        guard let content = frames["content"], let viewport = frames["viewport"] else { return nil }
        return content.minY - viewport.minY
    }
    private func navigationItem(at y: CGFloat) -> JSONValue? {
        guard !navigationItems.isEmpty, let origin = navigationContentOrigin else { return nil }
        let index = Int(floor((y - origin) / 10))
        return navigationItems[max(0, min(navigationItems.count - 1, index))]
    }
    private func keepNavigationVisible(_ anchor: String, proxy: ScrollViewProxy) {
        guard let index = navigationItems.firstIndex(where: { $0.stableID == anchor }),
              let origin = navigationContentOrigin else { return }
        let top = origin + CGFloat(index) * 10
        let height = min(180, CGFloat(navigationItems.count) * 10)
        if top < 0 { proxy.scrollTo(anchor, anchor: .top) }
        else if top + 10 > height { proxy.scrollTo(anchor, anchor: .bottom) }
    }
    private var navigationRail: some View {
        // Expansion belongs to the current gesture, not the last scroll destination.
        let center = navigationItems.firstIndex { $0.stableID == navigationPreview?.stableID } ?? -100
        return ScrollViewReader { proxy in
            ScrollView(.vertical) {
                VStack(spacing: 0) {
                    ForEach(Array(navigationItems.enumerated()), id: \.element.stableID) { index, item in
                        navigationButton(item, index: index, center: center)
                    }
                }.background(ConversationNavigationMarker(id: "content", tracker: navigationRailTracker))
            }.scrollIndicators(.hidden).frame(width: 32, height: min(180, CGFloat(navigationItems.count) * 10))
                .background(ConversationNavigationMarker(id: "viewport", tracker: navigationRailTracker))
                .highPriorityGesture(DragGesture(minimumDistance: 0)
                    .updating($navigationDragging) { _, active, _ in active = true }
                    .onChanged { value in
                        navigationPreview = navigationItem(at: value.location.y)
                    }.onEnded { value in
                        let target = navigationItem(at: value.location.y)?.stableID
                        navigationPreview = nil
                        if let target { navigate(to: target) }
                    })
                .onChange(of: navigationDragging) { _, active in
                    if !active { navigationPreview = nil }
                }
                .onContinuousHover { phase in
                    guard !navigationDragging else { return }
                    switch phase {
                    case .active(let point): navigationPreview = navigationItem(at: point.y)
                    case .ended: navigationPreview = nil
                    }
                }
                .onChange(of: navigationPreview?.stableID) { _, preview in
                    if let preview { keepNavigationVisible(preview, proxy: proxy) }
                }
                .onChange(of: navigationSelection) { _, anchor in
                    if let anchor, navigationPreview == nil { keepNavigationVisible(anchor, proxy: proxy) }
                }
        }.accessibilityLabel("对话消息导航")
    }
    private var composerCommandAllowed: Bool {
        guard model.draftComments.isEmpty, model.draftFiles.isEmpty, let command = ComposerCommand(ComposerDocument(text: model.draft, skills: model.draftSkills).wireText),
              ConversationCommands.available(command.name, model: model, target: actionTarget) else { return false }
        return !["plan", "side"].contains(command.name) || command.argument.isEmpty || model.canWrite(.send)
    }
    private var commandInputAllowed: Bool {
        model.canWrite && ComposerCommand.names.contains {
            ConversationCommands.available($0, model: model, target: actionTarget)
        }
    }
    @ViewBuilder private var composerView: some View {
        @Bindable var model = model
        if !model.conversationReadOnly {
        CarryOnChatComposer(text: $model.draft, skills: $model.draftSkills, selection: $model.draftSelection,
            disabled: !(model.canCompose || composerCommandAllowed || (model.state == "running" && model.canInteract(.stop))) || loadingImages || submitting,
            draftEditable: !loadingImages && !submitting && !model.writing,
            sendAllowed: composerCommandAllowed || (model.allows(model.editingMessage == .null ? .send : .edit) && !queueUnavailable), commandInputAllowed: commandInputAllowed, stopAllowed: model.canInteract(.stop),
            hasImages: !images.isEmpty || !model.draftSkills.isEmpty || !model.draftComments.isEmpty || !model.draftFiles.isEmpty, stopping: model.state == "running", submitting: submitting,
            resuming: supportsOperation("resume", in: model.history) && model.state == "idle" && model.history["controls"]["lastTurnStatus"].text == "interrupted" && model.editingMessage == .null,
            sendLabel: model.state == "running" ? (queueFollowUp ? "排队发送" : "补充到当前任务") : nil,
            send: submitMessage,
            stop: interruptTurn,
            resume: { Task { _ = await model.operation("resume", fields: ["turnId": model.history["controls"]["lastTurnId"]]) } }) {
                Menu {
                    PhotosPicker(selection: $photos, maxSelectionCount: max(1, 3 - images.count), matching: .images) {
                        Label("照片", systemImage: "photo")
                    }.disabled(images.count >= 3)
                    if model.history["controls"]["supportsFileReferences"].bool == true && model.allows(.files) {
                        Button { filesPicker = FilePanel(scope: model.scope, threadID: thread.id) } label: { Label("项目文件", systemImage: "doc") }
                    }
                    if model.history["controls"]["supportsMentions"].bool == true {
                        Button { mentionsPicker = true } label: { Label("应用与插件", systemImage: "at") }
                    }
                    if model.history["controls"]["supportsSkills"].bool == true {
                        Button { skillsPicker = true } label: { Label("技能", systemImage: "bolt") }
                    }
                } label: { Image(systemName: "plus").offset(x: 4).frame(width: 44, height: 44) }
                    .disabled(!model.canCompose || model.editingMessage != .null || loadingImages || submitting)
                    .accessibilityLabel("添加附件或技能")
                Menu {
                    Button { composerConfiguration = true } label: { Label("对话配置", systemImage: "gearshape") }
                    if model.state == "running", canQueue {
                        Button { queueFollowUps = true } label: { Label("排队发送 · 本轮结束后", systemImage: queueFollowUps ? "checkmark" : "text.badge.clock") }
                        Button { queueFollowUps = false } label: { Label("立即补充 · 当前任务", systemImage: !queueFollowUps ? "checkmark" : "arrow.turn.down.right") }.disabled(model.history["controls"]["canSteer"].bool == false)
                    }
                } label: { Image(systemName: "gearshape").offset(x: -4).frame(width: 44, height: 44) }.accessibilityLabel("对话配置")
                Spacer(minLength: 4)
                if let usage = ContextUsage(model.history["metadata"]["latestTokenUsageInfo"]) {
                    Button { contextInformation = true } label: {
                        ZStack {
                            Circle().stroke(Design.secondary.opacity(0.25), lineWidth: 2)
                            Circle().trim(from: 0, to: usage.fraction).stroke(Design.ink, style: StrokeStyle(lineWidth: 2, lineCap: .round)).rotationEffect(.degrees(-90))
                        }.frame(width: 18, height: 18).frame(width: 44, height: 44)
                    }.accessibilityLabel("上下文已用 \(usage.percentage)%")
                }
                Button { modelInfo = true } label: {
                    HStack(spacing: 4) {
                        Text(ModelPresentation.name(composerModel, catalog: model.cachedValue("/api/models"))).lineLimit(1).truncationMode(.middle)
                        Text(ModelPresentation.effort(composerEffort)).foregroundStyle(Design.secondary).lineLimit(1)
                    }.font(.subheadline).frame(minHeight: 44)
                }
                    .accessibilityLabel("模型与思考强度")
                if supportsOperation("voice-start", in: model.history) {
                    Button { showingVoice = true } label: { Image(systemName: "mic").frame(width: 44, height: 44) }.accessibilityLabel("语音聊天").disabled(!model.canInteract(.send))
                }
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
            if model.historyFailure == nil && model.history["syncing"].bool == true && !model.history["timeline"].array.isEmpty {
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
            if let query = ComposerCommand.query(model.draft), model.draftSkills.isEmpty, images.isEmpty, model.draftComments.isEmpty, model.draftFiles.isEmpty {
                let matches = ComposerCommand.names.filter { $0.hasPrefix(query) && ConversationCommands.available($0, model: model, target: actionTarget) }
                if !matches.isEmpty {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(matches, id: \.self) { name in
                                Button { model.draft = "/" + name; Task { await send() } } label: {
                                    Text("/" + name).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).padding(.horizontal, 12)
                                }.disabled(submitting)
                            }
                        }
                    }.frame(maxHeight: 220).background(Design.surface, in: RoundedRectangle(cornerRadius: 14))
                }
            }

            if !model.conversationReadOnly {
                if !model.connected && !model.commandReady && model.allows(.send) {
                    Text("可继续编辑草稿，连接恢复后可发送").font(.caption).foregroundStyle(Design.secondary)
                } else if (model.connected || model.commandReady) && !model.canCompose, let reason = model.interactionUnavailableReason(actionTarget, capability: .send) {
                    Text(reason).font(.caption).foregroundStyle(Design.secondary)
                }
                if queueUnavailable && !composerCommandAllowed { Text("当前任务暂不接受补充，请等待队列同步或任务结束。").font(.caption).foregroundStyle(Design.secondary) }
                ConversationActionBar(target: actionTarget)
            }

            if !model.draftFiles.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(model.draftFiles) { file in
                            Button { model.draftFiles.removeAll { $0.path == file.path } } label: {
                                HStack(spacing: 6) { Label(file.name, systemImage: "doc"); Image(systemName: "xmark") }
                                    .font(.subheadline).padding(.horizontal, 10).frame(minHeight: 44)
                            }.background(Design.input, in: RoundedRectangle(cornerRadius: 12))
                                .accessibilityLabel("移除文件引用 \(file.name)")
                                .disabled(submitting || model.writing || model.conversationReadOnly)
                        }
                    }
                }
            }
            if loadingImages { ProgressView().controlSize(.small) }
            if !model.draftComments.isEmpty {
                Button { commentPanel = CommentPanel(target: actionTarget) } label: {
                    Label("\(model.draftComments.count) 条待发送评论", systemImage: "text.bubble")
                }.font(.subheadline).frame(minHeight: 44)
            }
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
    private func returnToLatest() {
        navigationTracker.cancelReadingRestoration()
        newMessages = false; navigationPinned = false; pendingNavigation = nil
        model.activityScrollTarget = nil
        if let last = chatMessages.last { restoreScroll = ConversationListScroll(messageID: last.id, position: .bottom) }
    }
    @ViewBuilder private var latestButton: some View {
        if !bottomVisible {
            Button { returnToLatest() } label: {
                HStack(spacing: 6) {
                    if newMessages { Text("有新消息").font(.subheadline) }
                    Image(systemName: "chevron.down").font(.system(size: 18, weight: .medium))
                }.padding(.horizontal, newMessages ? 14 : 0)
                    .frame(minWidth: 44, minHeight: 44).background(Design.surface, in: Capsule())
                    .overlay(Capsule().stroke(Design.border, lineWidth: 1))
            }.accessibilityLabel(newMessages ? "有新消息，回到最新" : "回到最新")
                .accessibilityIdentifier("conversation-latest")
        }
    }
    private func send() async {
        guard !submitting, model.canWrite, !loadingImages else { return }
        let command = ComposerDocument(text: model.draft, skills: model.draftSkills).wireText.trimmingCharacters(in: .whitespacesAndNewlines)
        if let parsed = ComposerCommand(command) {
            guard images.isEmpty, model.draftSkills.isEmpty, model.draftComments.isEmpty, model.draftFiles.isEmpty else { model.report(APIError("此命令不接受图片、引用或评论，请先处理附件")); return }
            let source = model.draft, scope = model.scope, target = actionTarget
            submitting = true
            let effect = await ConversationCommands.execute(parsed, model: model, target: target)
            submitting = false
            guard model.scope == scope, model.selectedThread?.id == thread.id else { return }
            switch effect {
            case .side(let text): sideLaunch = SideLaunch(text: text, autoSend: true, sourceDraft: source, scope: scope, parentID: thread.id)
            case .panel(let name, let argument):
                if name == "model" { modelInfo = true }
                else { commandPanel = CommandPanel(name: name, argument: argument, scope: scope, sourceDraft: source) }
                if name != "fork", model.draft == source { model.draft = "" }
            case .completed: if model.draft == source { model.draft = "" }
            case .continueWith(let argument): if model.draft == source {
                model.draft = argument; submitting = true
                _ = await model.compose(images: [], queueFollowUp: queueFollowUp)
                submitting = false
            }
            case .failed: break
            }
            return
        }
        guard model.canCompose else { return }
        submitting = true; defer { submitting = false }
        if await model.compose(images: images.map(JSONValue.string), queueFollowUp: queueFollowUp) { photos = [] }
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
    @Environment(\.colorScheme) private var colorScheme
    @Environment(AppModel.self) private var model
    @Environment(\.conversationContentContext) private var contentContext
    let item: JSONValue
    let threadID: String
    private var canEdit: Bool { Self.canEdit(item, threadID: threadID, model: model, readOnly: contentContext.isReadOnly) }
    private var editAction: (@MainActor @Sendable () -> Void)? {
        guard canEdit else { return nil }
        let scope = model.scope
        return {
            guard model.scope == scope, Self.canEdit(item, threadID: threadID, model: model, readOnly: contentContext.isReadOnly) else { return }
            model.beginEditing(item)
        }
    }
    static func canEdit(_ item: JSONValue, threadID: String, model: AppModel, readOnly: Bool) -> Bool {
        item["type"].text == "userMessage" && item["turnId"] != .null && !readOnly &&
        supportsOperation("edit", in: model.history) && model.canInteract(.edit) && model.selectedThread?.id == threadID &&
        model.state == "idle" && model.history["syncing"].bool != true &&
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
                if user {
                    MessageThumbnails(parts: parts, refs: refs, threadID: threadID, alignTrailing: true)
                    MessageComposerReferences(skills: parts.filter { ["skill", "mention"].contains($0["type"].text) })
                }
                else { ForEach(refs.filter { $0["kind"].text == "image" }, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID, inlineImage: true) } }
                let messageText = user ? (item["displayText"].string ?? item["text"].text) : ConversationPresentation.attachmentDisplayText(item)
                if !messageText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    MessageMarkdown(text: messageText, artifacts: user ? [] : item["artifacts"].array, threadID: threadID, resolveCreatedThreads: !user)
                        .environment(\.colorScheme, user ? .dark : colorScheme)
                        .padding(user ? 13 : 0).background(user ? Color.black : .clear, in: RoundedRectangle(cornerRadius: 20))
                        .frame(maxWidth: .infinity, alignment: user ? .trailing : .leading)
                        .environment(\.editConversationMessage, editAction)
                        .accessibilityActions { if canEdit { Button("编辑消息") { model.beginEditing(item) } } }
                }
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
            if !model.allows(.files) { Image(systemName: "lock").accessibilityLabel("无文件查看权限") }
            else if let image { Button { model.previewImage = image } label: { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 88).clipped() }.buttonStyle(.plain).accessibilityLabel("打开原图") }
            else if let failure { Button { self.failure = nil } label: { Label("重试", systemImage: "arrow.clockwise").font(.caption) }.accessibilityHint(failure) }
            else { ProgressView().task { await load() } }
        }.frame(width: 88, height: 88).clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Design.border))
            .onChange(of: model.allows(.files)) { _, allowed in
                if !allowed { image = nil; model.previewImage = nil }
            }
    }
    private func load() async {
        guard model.allows(.files) else { return }
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
            guard model.allows(.files) else { return }
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
        !sending && model.canInteract(.edit) && !model.conversationReadOnly && model.scope == scope &&
        model.selectedThread?.id == threadID && model.editingMessage == item && model.state == "idle" &&
        model.history["syncing"].bool != true && item["turnId"] == model.history["controls"]["lastTurnId"] &&
        !model.editingDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
    var body: some View {
        @Bindable var model = model
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                TextEditor(text: $model.editingDraft).focused($focused)
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
    var configuration = false
    private var snapshot: JSONValue { model.snapshot(for: target) }
    @State private var choices: [JSONValue] = []
    @State private var selectedModel = ""
    @State private var effort = ""
    @State private var workMode = "default"
    @State private var approvalPolicy = "custom"
    @State private var loading = true
    @State private var saving = false
    @State private var failure: String?
    private var efforts: [String] { choices.first { $0["id"].text == selectedModel }?["efforts"].array.compactMap(\.string) ?? [] }
    var body: some View {
        NavigationStack {
            Form {
                if loading { ProgressView() }
                if !configuration {
                Picker("模型", selection: $selectedModel) {
                    if !choices.contains(where: { $0["id"].text == selectedModel }) { Text(selectedModel.isEmpty ? "未提供" : selectedModel).tag(selectedModel) }
                    ForEach(choices, id: \.stableID) { Text($0["name"].text).tag($0["id"].text) }
                }.pickerStyle(.menu).disabled(!supportsOperation("settings", in: snapshot) || choices.isEmpty || saving || !model.canPerform(target, action: "settings"))
                Picker("思考强度", selection: $effort) {
                    if !efforts.contains(effort) { Text(effort.isEmpty ? "未提供" : effort).tag(effort) }
                    ForEach(efforts, id: \.self) { Text($0).tag($0) }
                }.pickerStyle(.menu).disabled(!supportsOperation("settings", in: snapshot) || efforts.isEmpty || saving || !model.canPerform(target, action: "settings"))
                }
                if configuration {
                Picker("工作模式", selection: $workMode) {
                    Text("执行").tag("default")
                    Text("计划").tag("plan")
                }.disabled(saving || loading || !model.canPerform(target, action: "settings") || !snapshot["controls"]["supportedSettings"].array.contains(.string("collaborationMode")) || selectedModel.isEmpty)
                Picker("执行审批", selection: $approvalPolicy) {
                    Text("按需请求").tag("on-request")
                    Text("不可信命令请求").tag("untrusted")
                    Text("不请求").tag("never")
                    if approvalPolicy == "custom" { Text("当前自定义策略").tag("custom") }
                }.disabled(saving || loading || !model.canPerform(target, action: "settings") || !snapshot["controls"]["supportedSettings"].array.contains(.string("approvalPolicy")))
                }
                if let failure { Text(failure).foregroundStyle(.red) }
                if !loading && choices.isEmpty { Text("暂未读取到本机模型目录").foregroundStyle(Design.secondary) }
                if supportsOperation("settings", in: snapshot) { Text("从下一轮生效").font(.caption).foregroundStyle(Design.secondary) }
            }.navigationTitle(configuration ? "对话配置" : "模型与思考强度").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        if supportsOperation("settings", in: snapshot) { Button("保存") { Task {
                            saving = true
                            var settings: JSONValue = configuration ? .object([:]) : .object(["model": .string(selectedModel), "effort": .string(effort)])
                            if configuration, approvalPolicy != "custom", approvalPolicy != snapshot["controls"]["settings"]["approvalPolicy"].string { settings = settings.setting("approvalPolicy", .string(approvalPolicy)) }
                            if (configuration && workMode != (snapshot["controls"]["settings"]["collaborationMode"]["mode"].string ?? "default")) || (!configuration && snapshot["controls"]["settings"]["collaborationMode"] != .null) {
                                let previous = snapshot["controls"]["settings"]["collaborationMode"]["settings"]
                                settings = settings.setting("collaborationMode", .object(["mode": .string(workMode), "settings": .object([
                                    "model": .string(selectedModel), "reasoning_effort": .string(effort), "developer_instructions": previous["developer_instructions"]])]))
                            }
                            if settings.object?.isEmpty == true { saving = false; dismiss(); return }
                            if await model.perform("settings", target: target, fields: ["settings": settings]) { dismiss() }
                            saving = false
                        } }.disabled(saving || loading || !model.canPerform(target, action: "settings") || (!configuration && !efforts.contains(effort))) }
                    }
                }
                .task {
                    let scope = model.scope
                    loading = true; failure = nil
                    do {
                        let catalog = try await model.cachedDeviceRequest("/api/models", maxAge: 0)["models"].array
                        guard !Task.isCancelled, model.scope == scope else { return }
                        choices = catalog
                        workMode = snapshot["controls"]["settings"]["collaborationMode"]["mode"].string ?? "default"
                        selectedModel = snapshot["controls"]["settings"]["model"].string ?? snapshot["metadata"]["latestModel"].text
                        effort = snapshot["controls"]["settings"]["effort"].string ?? snapshot["metadata"]["latestReasoningEffort"].text
                        approvalPolicy = snapshot["controls"]["settings"]["approvalPolicy"].string ?? "custom"
                    } catch { if model.scope == scope { failure = error.localizedDescription } }
                    loading = false
                }
                .onChange(of: selectedModel) { _, value in
                    if !loading && !efforts.isEmpty && !efforts.contains(effort) {
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
            if !model.allows(.files) { Label("无文件查看权限", systemImage: "lock").font(.caption) }
            if model.allows(.files), !openOnLoad, ref["kind"].text != "image" { Button(ref["name"].text) { Task { await openFile() } }
                .font(.caption).bold().foregroundStyle(Design.link).disabled(loading || !model.allows(.files)).accessibilityHint("预览文件") }
            if model.allows(.files), !openOnLoad, let image {
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
                if model.allows(.files), ref["kind"].text != "image", let localFile { ShareLink(item: localFile) { Label("分享文件", systemImage: "square.and.arrow.up") } }
            }.font(.caption)
        }
        .frame(width: ref["kind"].text == "image" && !inlineImage ? 88 : nil, height: ref["kind"].text == "image" && !inlineImage ? 88 : nil)
        .frame(maxWidth: inlineImage ? .infinity : nil, alignment: .leading)
        .task(id: ref.stableID + String(model.allows(.files))) {
            guard model.allows(.files) else {
                image = nil; preview = nil; codeDocument = nil; model.previewImage = nil
                if let localFile { try? FileManager.default.removeItem(at: localFile.deletingLastPathComponent()) }
                localFile = nil
                return
            }
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
        guard model.allows(.files) else { return }
        await load()
        guard model.allows(.files), let localFile else { return }
        do {
            let data = try Data(contentsOf: localFile)
            if let document = CodeDocument(name: localFile.lastPathComponent, data: data) { codeDocument = document }
            else { preview = localFile }
        } catch { failure = error.localizedDescription }
    }
    private func load() async {
        guard model.allows(.files), localFile == nil, !loading else { return }
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
            guard !Task.isCancelled, model.allows(.files) else {
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
    var activityTarget: ConversationActionTarget? = nil
    private var target: ConversationActionTarget { activityTarget ?? .init(scope: model.scope, threadID: threadID, parentID: context.parentID) }
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
                                    .background(!useCustom && selected == option.text ? Design.ink : Design.input, in: Circle())
                                    .foregroundStyle(!useCustom && selected == option.text ? Design.onAccent : Design.secondary)
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
                        Button("发送") { Task { await send() } }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent)
                            .disabled(answer.isEmpty || answer == lastSubmission || !(model.canPerform(target) && model.allows(.send)) || submitting)
                    }.font(.caption)
                }.padding(16).background(Design.background, in: RoundedRectangle(cornerRadius: 18)).disabled(submitting)
            } else {
                Button { touched = true; expanded = true } label: {
                    Label(question["answer"] != .null ? "回答已同步" : submitted ? "回答已发送，等待同步" : "回答问题", systemImage: "questionmark.bubble")
                        .font(.caption).padding(.horizontal, 12).padding(.vertical, 8)
                        .overlay(Capsule().stroke(Design.border))
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
            if activityTarget == nil { do { try await Task.sleep(for: .seconds(30)); if !touched { expanded = false } } catch {} }
        }
        .onChange(of: question["answer"]) { _, value in if value != .null { submitted = true; lastSubmission = value.string; expanded = false } }
        .onChange(of: question["active"]) { _, value in if value.bool != true && !touched { expanded = false } }
    }
    private func send() async {
        guard !submitting, !answer.isEmpty, answer != lastSubmission, (model.canPerform(target) && model.allows(.send)) else { return }
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

private struct ConversationComposerBounds: PreferenceKey {
    static let defaultValue: Anchor<CGRect>? = nil
    static func reduce(value: inout Anchor<CGRect>?, nextValue: () -> Anchor<CGRect>?) { value = nextValue() ?? value }
}
