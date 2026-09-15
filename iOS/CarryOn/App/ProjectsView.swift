import SwiftUI
import CarryOnCore

struct ProjectsView: View {
    @Environment(AppModel.self) private var model
    @State private var creating = false
    @AppStorage("carryon.projectView") private var projectView = true
    var body: some View {
        @Bindable var model = model
        VStack(spacing: 0) {
            RecordListView(path: projectView ? "/api/projects" : "/api/workspace/threads",
                           key: projectView ? "projects" : "threads", isProjectList: projectView,
                           create: { creating = true }) { record in
                if projectView { model.selectedProject = record } else { model.open(record) }
            }.id(projectView)
        }
        .navigationDestination(isPresented: Binding(get: { model.selectedProject != nil }, set: { if !$0 { model.selectedProject = nil } })) {
            if let project = model.selectedProject {
                RecordListView(path: "/api/projects/\(ConsoleAddress.component(project.id))/threads", key: "threads") { model.open($0) }
                    .navigationTitle(project.title).navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .topBarTrailing) {
                        Button { creating = true } label: { Image(systemName: "plus") }.disabled(!model.canWrite).accessibilityLabel("新建会话")
                    } }
                    .navigationDestination(isPresented: Binding(get: { model.selectedThread != nil }, set: { if !$0 { model.closeThread() } })) {
                        if let thread = model.selectedThread { ConversationView(thread: thread).id(model.scope + thread.id) }
                    }
            }
        }.fullScreenCover(isPresented: $creating) { NewConversationView() }
    }
}
struct RecordListView: View {
    @Environment(AppModel.self) private var model
    let path: String
    let key: String
    var isProjectList = false
    var retainReadActivity = false
    var excludedThreadID: String?
    var create: (() -> Void)?
    let select: (Record) -> Void
    @State private var search = ""
    @State private var records: [Record] = []
    @State private var total = 0
    @State private var offset = 0
    private enum LoadKind { case initial, refresh, more, background }
    @State private var loadKind: LoadKind? = .initial
    private var loading: Bool { loadKind != nil }
    @State private var failure: String?
    @State private var requestVersion = UUID()
    @State private var clearing = false
    private var queryIdentity: String { model.scope + path + search + (excludedThreadID ?? "") }
    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 8) {
                SearchField(text: $search, placeholder: isProjectList ? "搜索项目" : "搜索会话")
            }.padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 12)
            ScrollView {
                VStack(spacing: 16) {
                    if records.isEmpty {
                        if model.selectedDevice.isEmpty { BlankState(text: "请先选择工作区", symbol: "laptopcomputer") }
                        else if loadKind == .initial { BlankState(text: "正在加载…", loading: true) }
                        else if let failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load(reset: true) } }) }
                        else if loadKind != .refresh {
                            BlankState(text: search.isEmpty ? (path == "/api/activity" ? "暂无动态" : "暂无\(isProjectList ? "项目" : "会话")") : "没有搜索结果", symbol: search.isEmpty ? (isProjectList ? "folder" : "bubble.left.and.bubble.right") : "magnifyingglass")
                        }
                    } else if let failure {
                        HStack { Text(failure).font(.caption).foregroundStyle(Design.secondary); Spacer(); Button("重试") { Task { await load(reset: true, kind: .background) } } }.padding(.vertical, 8)
                    }
                    if isProjectList {
                        LazyVStack(spacing: 12) {
                            ForEach(records) { record in
                                Button { select(record) } label: { Paper { projectRow(record) } }
                                    .buttonStyle(.plain)
                            }
                        }
                    } else if !records.isEmpty {
                        LazyVStack(spacing: 0) {
                            ForEach(records) { record in
                                Button { select(record) } label: { ThreadRow(record: record, dimmed: retainReadActivity && record.value["activityRead"].bool == true) }.buttonStyle(.plain)
                                if record.id != records.last?.id { Divider().padding(.leading, 16) }
                            }
                        }
                    }
                    if !records.isEmpty && records.count < total {
                        Button { Task { await load(reset: false, kind: .more) } } label: { if loadKind == .more { ProgressView("加载更多…") } else { Text("加载更多（\(records.count)/\(total)）").font(.caption) } }.frame(minHeight: 44).disabled(loading)
                    }
                }.padding(.bottom, 8)
            }.frame(minHeight: 0, maxHeight: .infinity)
                .background(isProjectList ? Color.clear : Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 19))
                .scrollDismissesKeyboard(.interactively)
                .refreshable { await load(reset: true, kind: .refresh) }
                .padding(.horizontal, 20).padding(.bottom, 12)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if create != nil || retainReadActivity {
                    ToolbarItem(placement: .topBarTrailing) {
                        if let create {
                            Button(action: create) { Image(systemName: "plus") }
                                .disabled(!model.canWrite).accessibilityLabel("新建会话")
                        } else if retainReadActivity {
                            Button("清空已读") { Task { await clearRead() } }
                                .disabled(clearing || loading || model.selectedDevice.isEmpty)
                        }
                    }
                }
            }
            .task(id: queryIdentity) { records = []; total = 0; offset = 0; await load(reset: true, debounce: !search.isEmpty) }
            .onChange(of: model.workspaceRevision) { _, _ in Task { await load(reset: true, kind: .background) } }
    }
    private func clearRead() async {
        clearing = true; defer { clearing = false }
        do {
            _ = try await model.deviceRequest("/api/notifications/clear-read", body: .object([:]))
            await load(reset: true, kind: .refresh)
            try await model.refreshActivityCounts()
        } catch { failure = error.localizedDescription }
    }
    private func projectRow(_ record: Record) -> some View {
        HStack(spacing: 14) {
            SymbolTile(name: "folder")
            VStack(alignment: .leading, spacing: 9) {
                Text(record.title).font(.system(size: 16, weight: .semibold))
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
        }.padding(.horizontal, 16).padding(.vertical, 21).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
    }
    @ViewBuilder private func counts(_ record: Record) -> some View {
        let waiting = record.value["waiting"].int ?? 0, running = record.value["running"].int ?? 0, unread = record.value["unread"].int ?? 0
        if waiting > 0 { CountPill(text: "\(waiting) 待处理", color: Design.orange) }
        if running > 0 { CountPill(text: "\(running) 进行中", color: Design.green) }
        if unread > 0 { CountPill(text: "\(unread) 未读", color: Design.blue) }
    }
    private func load(reset: Bool, kind: LoadKind = .initial, debounce: Bool = false) async {
        if (kind == .more || kind == .background) && loading { return }
        guard !model.selectedDevice.isEmpty else { loadKind = nil; return }
        let version = UUID(); requestVersion = version
        loadKind = kind; failure = nil
        defer { if requestVersion == version { loadKind = nil } }
        do {
            if debounce { try await Task.sleep(for: .milliseconds(300)) }
            try Task.checkCancellation()
            let excluded = excludedThreadID.map { "&excludeThreadId=" + ConsoleAddress.component($0) } ?? ""
            let next = try await model.page(path + "?limit=50&offset=\(reset ? 0 : offset)&search=\(ConsoleAddress.component(search))&filter=all" + excluded + (retainReadActivity ? "&includeRead=true" : ""), key: key)
            guard version == requestVersion, !Task.isCancelled else { return }
            let old = reset ? [] : records
            let ids = Set(old.map(\.id))
            records = old + next.records.filter { !ids.contains($0.id) }
            total = next.total; offset = next.nextOffset
        } catch {
            if !Task.isCancelled && version == requestVersion { failure = error.localizedDescription; model.report(error, operation: path == "/api/activity" ? "读取动态" : "读取会话列表", blocking: false) }
        }
    }
}
struct ActivityView: View {
    @Environment(AppModel.self) private var model
    @State private var links = false
    var body: some View {
        VStack(spacing: 0) {
            if !model.requests.isEmpty {
                Button { links = true } label: { SettingRow(icon: "link", title: "连接申请", value: "\(model.requests.count) 项待确认", chevron: true) }
                    .background(.white, in: RoundedRectangle(cornerRadius: 19)).padding(.horizontal, 20).padding(.top, 12)
            }
            RecordListView(path: "/api/activity", key: "threads", retainReadActivity: true) { model.open($0) }
        }.sheet(isPresented: $links) { ConnectionRequestsView() }
    }
}
