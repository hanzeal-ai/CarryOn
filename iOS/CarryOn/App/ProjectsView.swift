import SwiftUI
import CarryOnCore

@MainActor @Observable final class HomeNavigationState {
    var creating = false
    var creationProject: String? = nil
    var choosingWorkspace = false
    var browsingProjects = false
    var browsingThreads = false
    var searchingHome = false
    var browsingArchives = false
    var searchingContent = false
    var browsingSections = false
}

struct ProjectsView: View {
    @State var navigation = HomeNavigationState()
    @State var listState = RecordListState()
    @State var threadListState = RecordListState()
    @State var homeLoader = WorkspaceHomeLoader()
    @Environment(AppModel.self) private var model
    @AppStorage("carryon.showInactiveConversations") private var showInactiveConversations = false
    @State private var projectSearch = RecordListState()
    @State private var threadSearch = RecordListState()
    @State private var collapsedProjects: Set<String> = []
    @FocusState private var homeSearchFocused: Bool
    var body: some View {
        @Bindable var model = model
        ScrollViewReader { proxy in
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                workspaceFilters
                if model.status["supportsThreadSections"].bool == true { PinnedThreadsSummary { navigation.browsingSections = true } }
                VStack(alignment: .leading, spacing: 8) {
                    homeHeading("项目", more: listState.total > listState.records.count) { navigation.browsingProjects = true }
                    ForEach(listState.records) { project in
                        VStack(alignment: .leading, spacing: 0) {
                            HStack(spacing: 12) {
                                Button {
                                    if !collapsedProjects.insert(project.id).inserted { collapsedProjects.remove(project.id) }
                                } label: { HStack(spacing: 12) {
                                    Group {
                                        if collapsedProjects.contains(project.id) { Image(systemName: "folder").font(.system(size: 20)) }
                                        else { OpenProjectFolder().stroke(style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round)) }
                                    }.frame(width: 24, height: 22).accessibilityHidden(true)
                                    Text(project.title).font(.body).lineLimit(1)
                                    Spacer(minLength: 0)
                                }.frame(minHeight: 44).contentShape(Rectangle()) }
                                    .buttonStyle(.plain)
                                    .accessibilityValue(collapsedProjects.contains(project.id) ? "已收起" : "已展开")
                                    .accessibilityHint("原位展开或收起项目会话")
                                Button {
                                    navigation.creationProject = project.id
                                    navigation.creating = true
                                } label: { Image(systemName: "square.and.pencil").frame(width: 44, height: 44) }
                                    .foregroundStyle(Design.secondary).disabled(!model.canWrite(.create) || project.value["canCreate"].bool == false)
                                    .accessibilityLabel("在 " + project.title + " 新建会话")
                            }
                            if !collapsedProjects.contains(project.id) {
                            let threads = threadListState.records.filter { $0.value["projectId"].string == project.id }
                            ForEach(threads) { record in homeThread(record).padding(.leading, 32) }
                            if (project.value["total"].int ?? 0) > threads.count {
                                Button("查看全部") { model.selectedProject = project }
                                    .font(.subheadline).foregroundStyle(Design.secondary)
                                    .frame(minHeight: 44).padding(.leading, 32)
                            }
                            }
                        }.id(project.id)
                    }
                    homeStatus(listState)
                }
                let ungrouped = threadListState.records.filter { record in
                    !listState.records.contains { $0.id == record.value["projectId"].string }
                }
                if !ungrouped.isEmpty {
                    VStack(alignment: .leading, spacing: 0) {
                        homeHeading("最近会话", more: threadListState.total > threadListState.records.count) { navigation.browsingThreads = true }
                        ForEach(ungrouped) { record in homeThread(record) }
                    }
                }
                if threadListState.failure != nil || threadListState.records.isEmpty { homeStatus(threadListState) }
                if threadListState.total > threadListState.records.count {
                    Button("查看全部会话") { navigation.browsingThreads = true }
                        .font(.subheadline).foregroundStyle(Design.secondary).frame(minHeight: 44)
                }
            }.padding(.horizontal, 20).padding(.bottom, 20).frame(maxWidth: .infinity, alignment: .leading)
        }.scrollPosition(id: $listState.scrollID, anchor: .top).background(Design.canvas)
            .task {
                if let anchor = listState.scrollID {
                    await Task.yield()
                    if !Task.isCancelled { proxy.scrollTo(anchor, anchor: .top) }
                }
            }
        }
            .accessibilityHidden(navigation.searchingHome && !threadSearch.search.isEmpty)
            .overlay {
                if navigation.searchingHome && !threadSearch.search.isEmpty {
                    VStack(spacing: 8) {
                        workspaceFilters.padding(.horizontal, 20)
                        RecordListView(path: "/api/workspace/threads", key: "threads", controlsVisible: false, compactRows: true, state: threadSearch) { model.open($0) }
                    }.background(Design.canvas)
                }
            }
            .safeAreaInset(edge: .top, spacing: 0) {
                if navigation.searchingHome {
                    HStack(spacing: 12) {
                        HStack(spacing: 8) {
                            Image(systemName: "magnifyingglass").foregroundStyle(Design.secondary)
                            TextField("搜索聊天", text: $threadSearch.search).focused($homeSearchFocused)
                                .textInputAutocapitalization(.never).autocorrectionDisabled().submitLabel(.search)
                            if !threadSearch.search.isEmpty {
                                Button { threadSearch.search = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Design.secondary) }.accessibilityLabel("清除搜索")
                            }
                        }.padding(.horizontal, 14).frame(minHeight: 44).background(Design.input, in: Capsule())
                        Button { homeSearchFocused = false; threadSearch.search = ""; navigation.searchingHome = false } label: {
                            Image(systemName: "xmark").font(.title3).frame(width: 44, height: 44)
                        }.accessibilityLabel("关闭搜索")
                    }.padding(.horizontal, 20).padding(.vertical, 8).background(Design.canvas)
                        .onAppear { homeSearchFocused = true }
                }
            }
            .toolbar(navigation.searchingHome ? .hidden : .visible, for: .navigationBar)
            .refreshable { await loadHome(refresh: true, fullSync: true) }
            .task(id: model.scope) { projectSearch.reset(); threadSearch.reset(); await loadHome(refresh: false) }
            .onChange(of: model.scope) { _, _ in collapsedProjects = [] }
            .onChange(of: showInactiveConversations) { _, _ in Task { await loadHome(refresh: true) } }
            .onChange(of: model.workspaceRevision) { _, _ in Task { await loadHome(refresh: true) } }
            .onChange(of: model.connected) { _, connected in if connected { Task { await loadHome(refresh: true) } } }
            .onAppear { threadListState.isVisible = true; watchRecents() }
            .onDisappear { threadListState.isVisible = false; model.watchList(threadListState.watchID, threads: []) }
            .navigationTitle("CarryOn").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { navigation.searchingHome = true } label: {
                        Image(systemName: "magnifyingglass").frame(width: 44, height: 44)
                    }.accessibilityLabel("搜索会话")
                }.carryOnFlatToolbar()
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if !navigation.searchingHome {
                Button { navigation.creationProject = nil; navigation.creating = true } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "plus").font(.system(size: 22))
                        Text("向 CarryOn 提问").font(.body).foregroundStyle(Design.secondary)
                        Spacer(minLength: 0)
                        Image(systemName: "square.and.pencil").font(.system(size: 18))
                    }.padding(.horizontal, 16).frame(minHeight: 48)
                        .background(Design.input, in: Capsule())
                }.buttonStyle(.plain).disabled(!model.canWrite(.create)).accessibilityLabel("新建会话")
                    .padding(.horizontal, 32).padding(.vertical, 8).background(Design.canvas)
                }
            }
            .sheet(isPresented: $navigation.browsingSections) { NativeSectionsView() }
            .sheet(isPresented: $navigation.browsingArchives) { ArchivedThreadsView() }
            .sheet(isPresented: $navigation.searchingContent) { ConversationSearchView() }
            .sheet(isPresented: $navigation.browsingProjects) {
                NavigationStack {
                    RecordListView(path: "/api/projects", key: "projects", isProjectList: true, state: projectSearch) { record in navigation.browsingProjects = false; model.selectedProject = record }
                        .navigationTitle("项目").toolbar { ToolbarItem(placement: .cancellationAction) { Button("完成") { navigation.browsingProjects = false } } }
                }
            }
            .sheet(isPresented: $navigation.browsingThreads) {
                NavigationStack {
                    RecordListView(path: "/api/workspace/threads", key: "threads", state: threadSearch) { record in navigation.browsingThreads = false; model.open(record) }
                        .navigationTitle("会话").toolbar { ToolbarItem(placement: .cancellationAction) { Button("完成") { navigation.browsingThreads = false } } }
                }
            }
        .navigationDestination(isPresented: Binding(get: { model.selectedProject != nil }, set: { if !$0 { model.selectedProject = nil } })) {
            if let project = model.selectedProject {
                RecordListView(path: "/api/projects/\(ConsoleAddress.component(project.id))/threads", key: "threads") { model.open($0) }
                    .navigationTitle(project.title).navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .topBarTrailing) {
                        Button { navigation.creationProject = project.id; navigation.creating = true } label: { Image(systemName: "plus") }.disabled(!model.canWrite(.create)).accessibilityLabel("新建会话")
                    } }
                    .navigationDestination(isPresented: Binding(get: { model.selectedThread != nil }, set: { if !$0 { model.closeThread() } })) {
                        if let thread = model.selectedThread { ConversationView(thread: thread).id(model.scope + thread.id) }
                    }
            }
        }.background(Design.canvas)
            .sheet(isPresented: $navigation.choosingWorkspace) { WorkspaceSwitcher() }
            .fullScreenCover(isPresented: $navigation.creating) { NewConversationView(initialProject: navigation.creationProject) }
    }
    private var workspaceFilters: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Menu {
                    ForEach(model.workspaceGroups) { workspace in
                        Section(workspace.title) {
                            ForEach(workspace.connections) { connection in
                                Button { if connection.id != model.selectedDevice { model.switchDevice(connection.id) } } label: {
                                    Label(WorkspaceGroup.connectionLabel(connection), systemImage: connection.id == model.selectedDevice ? "checkmark" : "laptopcomputer")
                                }
                            }
                        }
                    }
                    Button("管理工作区") { navigation.choosingWorkspace = true }
                } label: {
                    HStack(spacing: 6) {
                        Circle().fill(model.connected ? Design.green : Design.secondary).frame(width: 5, height: 5)
                        Image(systemName: "laptopcomputer")
                        Text(model.selectedWorkspace?.title ?? model.device?.title ?? "工作区").lineLimit(1)
                        Image(systemName: "chevron.down").font(.caption2)
                    }.font(.subheadline).padding(.horizontal, 16).frame(minHeight: 44)
                        .background(Design.input, in: Capsule())
                }.buttonStyle(.plain).accessibilityLabel("切换工作区")
                if let workspace = model.selectedWorkspace, workspace.connections.count > 1 {
                    ForEach(workspace.connections) { connection in
                        Button { if connection.id != model.selectedDevice { model.switchDevice(connection.id) } } label: {
                            Text(WorkspaceGroup.connectionLabel(connection)).font(.subheadline)
                                .foregroundStyle(connection.id == model.selectedDevice ? Design.ink : Design.secondary)
                                .padding(.horizontal, 14).frame(minHeight: 44)
                                .background(connection.id == model.selectedDevice ? Design.input : .clear, in: Capsule())
                        }.buttonStyle(.plain)
                    }
                }
            }
        }.padding(.top, 8)
    }
    private func homeThread(_ record: Record) -> some View {
        Button { model.open(record) } label: {
            HStack(spacing: 10) {
                Text(record.title).font(.body).lineLimit(1).truncationMode(.tail)
                Spacer(minLength: 0)
                let state = model.listStatus(record)["state"].text
                if state == "running" { ProgressView().controlSize(.small) }
                else if state == "waiting" { Image(systemName: "exclamationmark.circle").foregroundStyle(Design.orange) }
                else if state == "error" || record.value["failed"].bool == true { Image(systemName: "exclamationmark.circle").foregroundStyle(.red) }
                else if ["unknown", "loading", "notLoaded"].contains(state) { Image(systemName: "questionmark.circle").foregroundStyle(Design.secondary) }
                else if record.value["unread"].bool == true { Circle().fill(Design.blue).frame(width: 7, height: 7) }
            }.frame(minHeight: 44).contentShape(Rectangle())
        }.buttonStyle(.plain).id(record.id)
            .accessibilityValue(model.listStatus(record)["label"].text)
            .onAppear { threadListState.visibleThreadIDs.insert(record.id); watchRecents() }
            .onDisappear { threadListState.visibleThreadIDs.remove(record.id); watchRecents() }
    }
    private func homeHeading(_ title: String, more: Bool, action: @escaping () -> Void) -> some View {
        HStack {
            Text(title).font(.subheadline.weight(.medium))
            Spacer()
            if more { Button("查看全部", action: action).font(.caption).foregroundStyle(Design.secondary).frame(minHeight: 44) }
        }.frame(minHeight: 28)
    }
    @ViewBuilder private func homeStatus(_ state: RecordListState) -> some View {
        if !state.records.isEmpty, let failure = state.failure {
            Button { Task { await loadHome(refresh: true) } } label: {
                Label("刷新失败，显示缓存 · " + failure, systemImage: "arrow.clockwise").font(.caption).foregroundStyle(Design.secondary)
            }.frame(minHeight: 44)
        }
        if state.records.isEmpty {
            if state.loadKind != nil { ProgressView().padding(.vertical, 12) }
            else if let failure = state.failure {
                Button { Task { await loadHome(refresh: true) } } label: { Label(failure + " · 重试", systemImage: "arrow.clockwise").font(.caption) }
            } else { Text("暂无内容").font(.subheadline).foregroundStyle(Design.secondary).padding(.vertical, 12) }
        }
    }
    private func watchRecents() {
        model.watchList(threadListState.watchID, threads: threadListState.isVisible ? threadListState.visibleThreadIDs : [])
    }
    private func loadHome(refresh: Bool, fullSync: Bool = false) async {
        await homeLoader.load(model: model, projects: listState, threads: threadListState,
                              includeInactive: showInactiveConversations, refresh: refresh, fullSync: fullSync)
    }

}
@MainActor @Observable final class RecordListState {
    enum LoadKind { case initial, refresh, more, background }
    var search = ""
    var filter = "all"
    var scrollID: String?
    var loadedQueryIdentity = ""
    var records: [Record] = []
    var total = 0
    var offset = 0
    var loadKind: LoadKind? = .initial
    var failure: String?
    var requestVersion = UUID()
    var clearing = false
    var updatedAt = Date.distantPast
    let watchID = UUID()
    var visibleThreadIDs: Set<String> = []
    var isVisible = false
    var refreshPending = false
    func reset() {
        search = ""; filter = "all"; scrollID = nil; loadedQueryIdentity = ""
        records = []; total = 0; offset = 0; loadKind = .initial
        failure = nil; requestVersion = UUID(); clearing = false; updatedAt = .distantPast
        visibleThreadIDs = []; refreshPending = false
    }
}

struct RecordListView: View {
    @AppStorage("carryon.showInactiveConversations") private var showInactiveConversations = false
    @Environment(AppModel.self) private var model
    let path: String
    let key: String
    var isProjectList = false
    var controlsVisible = true
    var compactRows = false
    var retainReadActivity = false
    var excludedThreadID: String?
    var beforeActivityOpen: (() -> Void)?
    var create: (() -> Void)?
    @State var state = RecordListState()
    let select: (Record) -> Void
    private typealias LoadKind = RecordListState.LoadKind
    private var loading: Bool { state.loadKind != nil }
    private var queryIdentity: String { model.scope + path + state.search + state.filter + String(showInactiveConversations) + (excludedThreadID ?? "") }
    var body: some View {
        VStack(spacing: 0) {
            if controlsVisible {
            VStack(spacing: 8) {
                SearchField(text: $state.search, placeholder: isProjectList ? "搜索项目" : "搜索会话")
                if !isProjectList {
                    Picker("筛选", selection: $state.filter) {
                        Text("全部").tag("all")
                        if path != "/api/activity" { Text("执行中").tag("running") }
                        Text("待处理").tag("waiting")
                        Text("未读").tag("unread")
                    }.pickerStyle(.segmented).accessibilityIdentifier("conversation-filter")
                }
            }.padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 12)
            }
            ScrollViewReader { proxy in
              ScrollView {
                VStack(spacing: 16) {
                    if state.records.isEmpty {
                        if model.selectedDevice.isEmpty { BlankState(text: "请先选择工作区", symbol: "laptopcomputer") }
                        else if state.loadKind == .initial { BlankState(text: "正在加载…", loading: true) }
                        else if let failure = state.failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load(reset: true) } }) }
                        else if state.loadKind != .refresh {
                            BlankState(text: state.search.isEmpty ? (path == "/api/activity" ? "暂无动态" : "暂无\(isProjectList ? "项目" : "会话")") : "未找到“\(state.search)”的结果", symbol: state.search.isEmpty ? (isProjectList ? "folder" : "bubble.left.and.bubble.right") : "magnifyingglass", detail: state.search.isEmpty ? nil : "请检查拼写或尝试其他关键词。")
                        }
                    } else if let failure = state.failure {
                        HStack { Text(failure).font(.caption).foregroundStyle(Design.secondary); Spacer(); Button("重试") { Task { await load(reset: true, kind: .background) } } }.padding(.vertical, 8)
                    }
                    if isProjectList {
                        LazyVStack(spacing: 0) {
                            ForEach(state.records) { record in
                                Button { select(record) } label: { projectRow(record) }
                                    .buttonStyle(.plain).id(record.id)
                            }
                        }.scrollTargetLayout()
                    } else if !state.records.isEmpty {
                        LazyVStack(spacing: 0) {
                            ForEach(state.records) { record in
                                if path == "/api/activity" {
                                    ActivityRow(record: record, scope: model.scope, dimmed: retainReadActivity && record.value["activityRead"].bool == true, beforeOpen: beforeActivityOpen)
                                        .id(record.id)
                                } else {
                                    Button { select(record) } label: { ThreadRow(record: record, compact: compactRows) }.buttonStyle(.plain).id(record.id)
                                        .onAppear { state.visibleThreadIDs.insert(record.id); syncListWatch() }
                                        .onDisappear { state.visibleThreadIDs.remove(record.id); syncListWatch() }
                                }
                                if !compactRows && record.id != state.records.last?.id { Divider().padding(.leading, 16) }
                            }
                        }.scrollTargetLayout()
                    }
                    if !state.records.isEmpty && state.records.count < state.total {
                        Button { Task { await load(reset: false, kind: .more) } } label: { if state.loadKind == .more { ProgressView("加载更多…") } else { Text("加载更多（\(state.records.count)/\(state.total)）").font(.caption) } }.frame(minHeight: 44).disabled(loading)
                    }
                }.padding(.bottom, 8)
            }.scrollPosition(id: $state.scrollID, anchor: .top).frame(minHeight: 0, maxHeight: .infinity)
                .background(Design.canvas)
                .scrollDismissesKeyboard(.interactively)
                .refreshable { await load(reset: true, kind: .refresh) }
                .padding(.horizontal, 20).padding(.bottom, 12)
                .task {
                    if let anchor = state.scrollID {
                        await Task.yield()
                        if !Task.isCancelled { proxy.scrollTo(anchor, anchor: .top) }
                    }
                }
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if create != nil || retainReadActivity {
                    ToolbarItem(placement: .topBarTrailing) {
                        if let create {
                            Button(action: create) { Image(systemName: "plus") }
                                .disabled(!model.canWrite(.create)).accessibilityLabel("新建会话")
                        } else if retainReadActivity {
                            Button("清空已读") { Task { await clearRead() } }
                                .disabled(state.clearing || loading || model.selectedDevice.isEmpty)
                        }
                    }
                }
            }
            .task(id: queryIdentity) {
                if state.loadedQueryIdentity == queryIdentity {
                    if Date().timeIntervalSince(state.updatedAt) < 30 { return }
                    await load(reset: true, kind: state.records.isEmpty ? .initial : .background)
                    return
                }
                state.loadedQueryIdentity = queryIdentity
                state.records = []; state.total = 0; state.offset = 0; state.scrollID = nil
                if let cached = try? RecordPage(model.cachedValue(requestPath(offset: 0)), key: key) {
                    state.records = cached.records; state.total = cached.total; state.offset = cached.nextOffset
                }
                await load(reset: true, debounce: !state.search.isEmpty)
            }
            .onChange(of: model.connected) { _, connected in
                if connected { Task { await load(reset: true, kind: .background) } }
            }
            .onChange(of: model.workspaceRevision) { _, _ in Task { await load(reset: true, kind: .background) } }
            .onAppear { state.isVisible = true; syncListWatch() }
            .onDisappear { state.isVisible = false; model.watchList(state.watchID, threads: []) }
            .onChange(of: model.scope) { _, _ in state.visibleThreadIDs = []; syncListWatch() }
            .onChange(of: model.activitySnapshots.isEmpty) { _, empty in
                if path == "/api/activity", empty { Task { await load(reset: true, kind: .background) } }
            }
    }
    private func syncListWatch() {
        guard !isProjectList, path != "/api/activity", state.isVisible else { return }
        model.watchList(state.watchID, threads: state.visibleThreadIDs)
    }
    private func clearRead() async {
        state.clearing = true; defer { state.clearing = false }
        do {
            _ = try await model.deviceRequest("/api/notifications/clear-read", body: .object([:]))
            await load(reset: true, kind: .refresh)
            try await model.refreshActivityCounts()
        } catch { state.failure = error.localizedDescription }
    }
    private func projectRow(_ record: Record) -> some View {
        HStack(spacing: 14) {
            SymbolTile(name: "folder")
            VStack(alignment: .leading, spacing: 6) {
                Text(record.title).font(.body.weight(.medium))
                Text("\(record.value["total"].int ?? 0) 个会话").font(.caption).foregroundStyle(Design.secondary)
                if ["waiting", "running", "unread"].contains(where: { (record.value[$0].int ?? 0) > 0 }) {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 5) { counts(record) }
                        VStack(alignment: .leading, spacing: 5) { counts(record) }
                    }
                }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
        }.padding(.horizontal, 4).padding(.vertical, 12).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
    }
    @ViewBuilder private func counts(_ record: Record) -> some View {
        let waiting = record.value["waiting"].int ?? 0, running = record.value["running"].int ?? 0, unread = record.value["unread"].int ?? 0
        if waiting > 0 { CountPill(text: "\(waiting) 待处理", color: Design.orange) }
        if running > 0 && model.connected { CountPill(text: "\(running) 进行中", color: Design.green) }
        if unread > 0 { CountPill(text: "\(unread) 未读", color: Design.blue) }
    }
    private func requestPath(offset requestedOffset: Int, refreshStatuses: Bool = false) -> String {
        let excluded = excludedThreadID.map { "&excludeThreadId=" + ConsoleAddress.component($0) } ?? ""
        return path + "?limit=50&offset=\(requestedOffset)&search=\(ConsoleAddress.component(state.search))&filter=\(state.filter)&availableOnly=\(!showInactiveConversations)" + excluded + (retainReadActivity ? "&includeRead=true" : "") + (refreshStatuses ? "&refreshStatuses=true&sync=full" : "")
    }
    private func load(reset: Bool, kind: LoadKind = .initial, debounce: Bool = false) async {
        if (kind == .more || kind == .background) && loading {
            if kind == .background { state.refreshPending = true }
            return
        }
        // Reading a detail may remove its row from the unread query. Keep its sheet alive until dismissed.
        if path == "/api/activity", !model.activitySnapshots.isEmpty { return }
        guard !model.selectedDevice.isEmpty else { state.loadKind = nil; return }
        let version = UUID(); state.requestVersion = version
        state.loadKind = kind; state.failure = nil
        defer {
            if state.requestVersion == version {
                state.loadKind = nil
                let refresh = state.refreshPending
                state.refreshPending = false
                if refresh, state.isVisible, !Task.isCancelled {
                    Task { await load(reset: true, kind: .background) }
                }
            }
        }
        do {
            if debounce { try await Task.sleep(for: .milliseconds(300)) }
            try Task.checkCancellation()
            let desired = reset && kind == .background ? max(50, state.records.count) : 50
            let request = requestPath(offset: reset ? 0 : state.offset, refreshStatuses: kind == .refresh)
            var value = try await model.cachedDeviceRequest(request, maxAge: kind == .initial ? 30 : 0)
            if kind == .refresh && value["sync"]["state"].string == nil {
                throw APIError("工作区服务尚不支持完整同步，请更新桌面端 CarryOn")
            }
            while value["sync"]["state"].string == "running" {
                guard version == state.requestVersion, !Task.isCancelled else { return }
                guard let syncID = value["sync"]["id"].string else { throw APIError("同步响应缺少标识") }
                try await Task.sleep(for: .milliseconds(500))
                value = try await model.cachedDeviceRequest(requestPath(offset: 0) + "&syncId=" + ConsoleAddress.component(syncID), maxAge: 0)
            }
            if value["sync"]["state"].string == "failed" { throw APIError(value["sync"]["error"].string ?? "工作区同步失败，请重试") }
            if kind == .refresh && value["sync"]["state"].string != "completed" {
                throw APIError("未收到同步完成确认，请重试")
            }
            var next = try RecordPage(value, key: key)
            var refreshed = next.records
            while reset && refreshed.count < min(desired, next.total) && !next.records.isEmpty {
                guard version == state.requestVersion, !Task.isCancelled else { return }
                next = try RecordPage(try await model.cachedDeviceRequest(requestPath(offset: next.nextOffset), maxAge: 0), key: key)
                refreshed += next.records
            }
            guard version == state.requestVersion, !Task.isCancelled else { return }
            if path == "/api/activity", !model.activitySnapshots.isEmpty { return }
            let old = reset ? [] : state.records
            let ids = Set(old.map(\.id))
            state.records = old + refreshed.filter { !ids.contains($0.id) }
            state.total = next.total; state.offset = next.nextOffset; state.updatedAt = Date()
        } catch {
            if !Task.isCancelled && version == state.requestVersion { state.failure = error.localizedDescription; model.report(error, operation: path == "/api/activity" ? "读取动态" : "读取会话列表", blocking: false) }
        }
    }
}
struct ActivityView: View {
    @State var listState = RecordListState()
    @Environment(AppModel.self) private var model
    @State private var links = false
    var body: some View {
        VStack(spacing: 0) {
            if !model.requests.isEmpty {
                Button { links = true } label: { SettingRow(icon: "link", title: "连接申请", value: "\(model.requests.count) 项待确认", chevron: true) }
                    .background(Design.surface, in: RoundedRectangle(cornerRadius: Design.corner)).padding(.horizontal, 20).padding(.top, 12)
            }
            RecordListView(path: "/api/activity", key: "threads", retainReadActivity: true, state: listState) { model.open($0) }
        }.sheet(isPresented: $links) { NavigationStack { ScrollView { WorkspaceBindingRequests().padding(20) }.navigationTitle("连接申请") } }
    }
}

private struct OpenProjectFolder: Shape {
    func path(in rect: CGRect) -> Path {
        Path { path in
            path.move(to: CGPoint(x: 2, y: 19))
            path.addLine(to: CGPoint(x: 2, y: 6))
            path.addQuadCurve(to: CGPoint(x: 4, y: 4), control: CGPoint(x: 2, y: 4))
            path.addLine(to: CGPoint(x: 9, y: 4))
            path.addLine(to: CGPoint(x: 12, y: 7))
            path.addLine(to: CGPoint(x: 20, y: 7))
            path.addQuadCurve(to: CGPoint(x: 22, y: 9), control: CGPoint(x: 22, y: 7))
            path.move(to: CGPoint(x: 2, y: 19))
            path.addLine(to: CGPoint(x: 6, y: 10))
            path.addLine(to: CGPoint(x: 23, y: 10))
            path.addLine(to: CGPoint(x: 19, y: 19))
            path.closeSubpath()
        }.applying(CGAffineTransform(scaleX: rect.width / 24, y: rect.height / 22))
    }
}
