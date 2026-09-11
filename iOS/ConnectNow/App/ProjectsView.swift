import SwiftUI
import ConnectNowCore

struct ProjectsView: View {
    @Environment(AppModel.self) private var model
    @State private var creating = false
    var body: some View {
        @Bindable var model = model
        RecordListView(path: "/api/projects", key: "projects", isProjectList: true, create: { creating = true }) { model.selectedProject = $0 }
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
    var create: (() -> Void)?
    let select: (Record) -> Void
    @State private var search = ""
    @State private var records: [Record] = []
    @State private var total = 0
    @State private var offset = 0
    @State private var loading = false
    @State private var failure: String?
    @State private var requestVersion = UUID()
    private var queryIdentity: String { model.scope + path + search }
    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                HStack(spacing: 8) {
                    SearchField(text: $search, placeholder: isProjectList ? "搜索项目" : "搜索会话")
                    if let create { Button(action: create) { Image(systemName: "plus").font(.system(size: 25)).frame(width: 44, height: 44) }.disabled(!model.canWrite).accessibilityLabel("新建会话") }
                }.padding(.top, 12)
                if let failure {
                    VStack { Text(failure).font(.subheadline).foregroundStyle(Design.secondary); Button("重试") { Task { await load(reset: true) } }.frame(minHeight: 44) }.padding()
                }
                if records.isEmpty && failure == nil { BlankState(text: loading ? "正在读取…" : "暂无\(isProjectList ? "项目" : "匹配的会话")", loading: loading) }
                Paper {
                    ForEach(records) { record in
                        Button { select(record) } label: {
                            if isProjectList { projectRow(record) } else { ThreadRow(record: record) }
                        }.buttonStyle(.plain)
                        if record.id != records.last?.id { Divider().padding(.leading, 16) }
                    }
                }
                if records.count < total {
                    Button { Task { await load(reset: false) } } label: { if loading { ProgressView() } else { Text("加载更多（\(records.count)/\(total)）").font(.caption) } }.frame(minHeight: 44).disabled(loading)
                }
            }.padding(.horizontal, 20).padding(.bottom, 24)
        }.scrollDismissesKeyboard(.interactively).refreshable { await load(reset: true) }
            .task(id: queryIdentity) { records = []; await load(reset: true) }
            .onChange(of: model.workspaceRevision) { _, _ in Task { await load(reset: true) } }
    }
    private func projectRow(_ record: Record) -> some View {
        HStack(spacing: 14) {
            SymbolTile(name: "chevron.left.forwardslash.chevron.right")
            VStack(alignment: .leading, spacing: 9) {
                Text(record.title).font(.system(size: 16, weight: .semibold))
                Text("\(record.value["total"].int ?? 0) 个会话").font(.caption).foregroundStyle(Design.secondary)
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 5) { counts(record) }
                    VStack(alignment: .leading, spacing: 5) { counts(record) }
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
        if waiting + running + unread == 0 { CountPill(text: (record.value["unknown"].int ?? 0) > 0 ? "部分状态未知" : "暂无进行中的任务") }
    }
    private func load(reset: Bool) async {
        if !reset && loading { return }
        let version = UUID(); requestVersion = version
        loading = true; failure = nil
        defer { if requestVersion == version { loading = false } }
        do {
            let next = try await model.page(path + "?limit=50&offset=\(reset ? 0 : offset)&search=\(ConsoleAddress.component(search))&filter=all", key: key)
            guard version == requestVersion, !Task.isCancelled else { return }
            let old = reset ? [] : records
            let ids = Set(old.map(\.id))
            records = old + next.records.filter { !ids.contains($0.id) }
            total = next.total; offset = next.nextOffset
        } catch {
            if !Task.isCancelled && version == requestVersion { failure = error.localizedDescription; if (error as? APIError)?.status == 401 { model.report(error) } }
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
            RecordListView(path: "/api/activity", key: "threads") { model.open($0) }
        }.sheet(isPresented: $links) { ConnectionRequestsView() }
    }
}
