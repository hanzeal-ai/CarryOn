import SwiftUI
import CarryOnCore
import ExyteChat

func supportsOperation(_ action: String, in snapshot: JSONValue) -> Bool {
    snapshot["controls"]["supportedOperations"] == .null || snapshot["controls"]["supportedOperations"].array.contains(.string(action))
}

struct NewConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var projects: [Record] = []
    @State private var project = ""
    @State private var selecting = false
    private var directCreation: Bool { model.status["supportsDirectCreation"].bool == true }
    private var text: String { model.draftStore.texts[model.scope + "\nnew"] ?? "" }
    private var draftBinding: Binding<String> {
        Binding(get: { text }, set: { model.draftStore.texts[model.scope + "\nnew"] = $0 })
    }
    @State private var failure: String?
    @State private var loading = false
    @State private var offset = 0
    @State private var hasMore = true
    @State private var loadVersion = UUID()
    var body: some View {
        NavigationStack {
            ChatView(messages: [], didSendMessage: { _ in }, inputViewBuilder: { _ in
                CarryOnChatComposer(text: draftBinding, disabled: !model.canWrite(.create) || (!directCreation && !projects.contains(where: { $0.id == project })) || loading,
                                    send: { Task { await create() } }) { EmptyView() }
            })
            .setAvailableInputs([.text])
            .mainHeaderBuilder {
                VStack(alignment: .leading, spacing: 16) {
                    if !directCreation {
                    SectionCaption(title: "项目")
                    Paper {
                        Button { selecting = true } label: { SettingRow(icon: "folder", title: projects.first(where: { $0.id == project })?.title ?? "选择项目", chevron: true) }
                    }
                    }
                    if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                }.padding(20)
            }
            .carryOnChatAppearance()
            .disabled(loading)
            .navigationTitle("新建会话").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .task(id: model.scope) { projects = []; project = model.selectedProject?.id ?? ""; await loadProjects(reset: true) }
                .sheet(isPresented: $selecting) {
                    NavigationStack {
                        List {
                            ForEach(projects) { item in Button { project = item.id; selecting = false } label: { HStack { Text(item.title); Spacer(); if project == item.id { Image(systemName: "checkmark") } } } }
                            if hasMore { Button("加载更多") { Task { await loadProjects(reset: false) } }.disabled(loading) }
                            if let failure { Text(failure).foregroundStyle(.red) }
                            if projects.isEmpty && !loading && failure == nil { Text("暂无可用项目").foregroundStyle(Design.secondary) }
                        }.navigationTitle("选择项目").navigationBarTitleDisplayMode(.inline)
                            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { selecting = false } } }
                    }
                }
        }
    }
    private func loadProjects(reset: Bool) async {
        if directCreation { return }
        let scope = model.scope, version = UUID(); loadVersion = version
        loading = true; defer { if loadVersion == version { loading = false } }
        do {
            let result = try await model.deviceRequest("/api/projects?limit=50&offset=\(reset ? 0 : offset)")
            guard scope == model.scope, loadVersion == version, !Task.isCancelled else { return }
            guard case .array(let rows) = result["projects"] else { throw APIError("项目目录格式不正确") }
            let items = try rows.filter { !$0["cwd"].text.isEmpty || $0["canCreate"].bool == true }.map(Record.init)
            projects = reset ? items : projects + items.filter { item in !projects.contains { $0.id == item.id } }
            if project.isEmpty, projects.count == 1 { project = projects[0].id }
            offset = result["nextOffset"].int ?? offset + items.count; hasMore = offset < (result["total"].int ?? offset); failure = nil
        } catch { if scope == model.scope && loadVersion == version && !Task.isCancelled { failure = error.localizedDescription } }
    }
    private func create() async {
        guard model.canWrite(.create), directCreation || projects.contains(where: { $0.id == project }) else { return }
        loading = true; defer { loading = false }
        let draftKey = model.scope + "\nnew", sent = text
        var fields: [String: JSONValue] = ["prompt": .string(sent)]
        if !directCreation { fields["projectId"] = .string(project) }
        if await model.write(path: "/api/threads", target: "new:" + project, body: .object(fields)) {
            if model.draftStore.texts[draftKey] == sent { model.draftStore.texts[draftKey] = ""; model.draftStore.save() }
            dismiss()
        }
    }
}
struct ConversationMenu: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var jobs = false
    @State private var metadata = false
    @State private var sideChats = false
    @State private var subagents = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    Paper {
                        Button { subagents = true } label: { SettingRow(icon: "person.2", title: "子会话", chevron: true) }
                        Divider().padding(.leading, 60)
                        Button { sideChats = true } label: { SettingRow(icon: "bubble.left.and.bubble.right", title: "临时聊天", chevron: true) }
                        Divider().padding(.leading, 60)
                        Button { metadata = true } label: { SettingRow(icon: "info.circle", title: "会话信息", chevron: true) }
                        Divider().padding(.leading, 60)
                        if let thread = model.selectedThread, !model.conversationReadOnly {
                            Button {
                                let target = ConversationActionTarget(scope: model.scope, threadID: thread.id)
                                Task { if await model.perform("compact", target: target) { dismiss() } }
                            } label: { SettingRow(icon: "arrow.down.right.and.arrow.up.left", title: "压缩上下文") }
                                .disabled(!model.canInteract(.edit) || model.state != "idle" || !model.history["controls"]["requests"].array.isEmpty)
                            Divider().padding(.leading, 60)
                        }
                        Button { jobs = true } label: { SettingRow(icon: "clock", title: "请求记录", chevron: true) }
                    }
                }.padding(20)
            }.background(Design.background).navigationTitle("会话操作").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .sheet(isPresented: $jobs) { RequestLogView() }
                .sheet(isPresented: $sideChats) { SideChatsView() }
                .sheet(isPresented: $subagents) {
                    if let parent = model.selectedThread?.id { SubagentsView(parentID: parent, onOpen: { dismiss() }) }
                }
                .sheet(isPresented: $metadata) { StructuredDetail(title: "会话信息", value: model.history["metadata"]) }

        }.presentationDetents([.medium, .large])
    }
}
struct RequestLogView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var records: [Record] = []
    @State private var failure: String?
    @State private var loading = true
    @State private var refreshing = false
    @State private var version = UUID()
    @State private var confirmedJob: Record?
    var body: some View {
        NavigationStack {
            List {
                if let failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load() } }) }
                ForEach(records) { record in
                    DisclosureGroup(record.value["kind"].text + " · " + record.value["state"].text) {
                        Text(record.value.formatted).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        if ["uncertain", "failed"].contains(record.value["state"].text) {
                            Button("我已在 Codex App 核对结果") { confirmedJob = record }.disabled(!model.canWrite(.send))
                        }
                    }
                }
                if records.isEmpty && failure == nil && !refreshing { BlankState(text: loading ? "正在加载请求记录…" : "暂无请求记录", loading: loading, symbol: "clock") }
                Text("请求已登记不代表任务已完成。结果不确定时，请先在 Codex App 核对，保留原内容与请求编号。").font(.caption).foregroundStyle(Design.secondary)
            }.navigationTitle("请求记录").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .task { await load() }.refreshable { await load(refresh: true) }
                .alert("确认已在 Codex App 核对实际结果？", isPresented: Binding(get: { confirmedJob != nil }, set: { if !$0 { confirmedJob = nil } })) {
                    Button("取消", role: .cancel) { confirmedJob = nil }
                    Button("已核对") { if let record = confirmedJob { Task { await model.confirmJob(record.value); await load() } }; confirmedJob = nil }
                } message: { Text("这仅解除当前请求的待核对状态，不会重新发送任务，也不表示原任务执行成功。") }
        }
    }
    private func load(refresh: Bool = false) async {
        let request = UUID(); version = request
        refreshing = refresh; loading = !refresh; failure = nil
        defer { if request == version { loading = false; refreshing = false } }
        do {
            let value = try await model.deviceRequest("/api/jobs")
            guard request == version, !Task.isCancelled else { return }
            guard case .array(let items) = value["jobs"] else { throw APIError("请求记录格式不正确") }
            records = try items.map(Record.init); model.reconcile(items)
        } catch { if request == version && !Task.isCancelled { failure = error.localizedDescription } }
    }
}
