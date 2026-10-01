import SwiftUI
import CarryOnCore

struct ProjectsView: View {
    @State var listState = RecordListState()
    @State var threadListState = RecordListState()
    @Environment(AppModel.self) private var model
    @State private var creating = false
    @AppStorage("carryon.projectView") private var projectView = true
    var body: some View {
        @Bindable var model = model
        VStack(spacing: 0) {
            RecordListView(path: projectView ? "/api/projects" : "/api/workspace/threads",
                           key: projectView ? "projects" : "threads", isProjectList: projectView,
                           create: { creating = true }, state: projectView ? listState : threadListState) { record in
                if projectView { model.selectedProject = record } else { model.open(record) }
            }.id(projectView)
        }
        .navigationDestination(isPresented: Binding(get: { model.selectedProject != nil }, set: { if !$0 { model.selectedProject = nil } })) {
            if let project = model.selectedProject {
                RecordListView(path: "/api/projects/\(ConsoleAddress.component(project.id))/threads", key: "threads") { model.open($0) }
                    .navigationTitle(project.title).navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .topBarTrailing) {
                        Button { creating = true } label: { Image(systemName: "plus") }.disabled(!model.canWrite(.create)).accessibilityLabel("新建会话")
                    } }
                    .navigationDestination(isPresented: Binding(get: { model.selectedThread != nil }, set: { if !$0 { model.closeThread() } })) {
                        if let thread = model.selectedThread { ConversationView(thread: thread).id(model.scope + thread.id) }
                    }
            }
        }.fullScreenCover(isPresented: $creating) { NewConversationView() }
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
            ScrollViewReader { proxy in
              ScrollView {
                VStack(spacing: 16) {
                    if state.records.isEmpty {
                        if model.selectedDevice.isEmpty { BlankState(text: "请先选择工作区", symbol: "laptopcomputer") }
                        else if state.loadKind == .initial { BlankState(text: "正在加载…", loading: true) }
                        else if let failure = state.failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load(reset: true) } }) }
                        else if state.loadKind != .refresh {
                            BlankState(text: state.search.isEmpty ? (path == "/api/activity" ? "暂无动态" : "暂无\(isProjectList ? "项目" : "会话")") : "没有搜索结果", symbol: state.search.isEmpty ? (isProjectList ? "folder" : "bubble.left.and.bubble.right") : "magnifyingglass")
                        }
                    } else if let failure = state.failure {
                        HStack { Text(failure).font(.caption).foregroundStyle(Design.secondary); Spacer(); Button("重试") { Task { await load(reset: true, kind: .background) } } }.padding(.vertical, 8)
                    }
                    if isProjectList {
                        LazyVStack(spacing: 12) {
                            ForEach(state.records) { record in
                                Button { select(record) } label: { Paper { projectRow(record) } }
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
                                    Button { select(record) } label: { ThreadRow(record: record) }.buttonStyle(.plain).id(record.id)
                                        .onAppear { state.visibleThreadIDs.insert(record.id); syncListWatch() }
                                        .onDisappear { state.visibleThreadIDs.remove(record.id); syncListWatch() }
                                }
                                if record.id != state.records.last?.id { Divider().padding(.leading, 16) }
                            }
                        }.scrollTargetLayout()
                    }
                    if !state.records.isEmpty && state.records.count < state.total {
                        Button { Task { await load(reset: false, kind: .more) } } label: { if state.loadKind == .more { ProgressView("加载更多…") } else { Text("加载更多（\(state.records.count)/\(state.total)）").font(.caption) } }.frame(minHeight: 44).disabled(loading)
                    }
                }.padding(.bottom, 8)
            }.scrollPosition(id: $state.scrollID, anchor: .top).frame(minHeight: 0, maxHeight: .infinity)
                .background(isProjectList ? Color.clear : Design.surface)
                .clipShape(RoundedRectangle(cornerRadius: Design.corner))
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
        }.padding(.horizontal, 16).padding(.vertical, 16).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
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
