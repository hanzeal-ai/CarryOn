import SwiftUI
import CarryOnCore
import ExyteChat

struct NewConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var controllers: [Record] = []
    @State private var controller = ""
    @State private var selecting = false
    private var text: String { model.drafts[model.scope + "\nnew"] ?? "" }
    private var draftBinding: Binding<String> {
        Binding(get: { text }, set: { model.drafts[model.scope + "\nnew"] = $0 })
    }
    @State private var failure: String?
    @State private var loading = false
    @State private var offset = 0
    @State private var hasMore = true
    var body: some View {
        NavigationStack {
            ChatView(messages: [], didSendMessage: { _ in }, inputViewBuilder: { _ in
                CarryOnChatComposer(text: draftBinding, disabled: !model.canWrite || controller.isEmpty || loading,
                                    send: { Task { await create() } }) { EmptyView() }
            })
            .setAvailableInputs([.text])
            .mainHeaderBuilder {
                VStack(alignment: .leading, spacing: 16) {
                    SectionCaption(title: "控制会话")
                    Paper {
                        Button { selecting = true } label: { SettingRow(icon: "bubble", title: controllers.first(where: { $0.id == controller })?.title ?? "选择控制会话", chevron: true) }
                    }
                    Text("通过电脑端已打开的控制会话创建新会话。").font(.caption).foregroundStyle(Design.secondary)
                    if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                }.padding(20)
            }
            .carryOnChatAppearance()
            .disabled(loading)
            .navigationTitle("新建会话").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .task { controller = model.status["controllerId"].text; await loadControllers(reset: true) }
                .sheet(isPresented: $selecting) {
                    NavigationStack {
                        List {
                            ForEach(controllers) { item in Button { controller = item.id; selecting = false } label: { HStack { Text(item.title); Spacer(); if controller == item.id { Image(systemName: "checkmark") } } } }
                            if hasMore { Button("加载更多") { Task { await loadControllers(reset: false) } }.disabled(loading) }
                            if let failure { Text(failure).foregroundStyle(.red) }
                        }.navigationTitle("选择控制会话").navigationBarTitleDisplayMode(.inline)
                            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { selecting = false } } }
                    }
                }
        }
    }
    private func loadControllers(reset: Bool) async {
        loading = true; defer { loading = false }
        do {
            let result = try await model.deviceRequest("/api/threads?limit=50&offset=\(reset ? 0 : offset)")
            guard case .array(let rows) = result["threads"] else { throw APIError("会话目录格式不正确") }
            let items = try rows.map(Record.init)
            controllers = reset ? items : controllers + items.filter { item in !controllers.contains { $0.id == item.id } }
            offset = result["nextOffset"].int ?? offset + items.count; hasMore = items.count == 50; failure = nil
        } catch { failure = error.localizedDescription }
    }
    private func create() async {
        guard model.canWrite else { return }
        loading = true; defer { loading = false }
        do {
            _ = try await model.deviceRequest("/api/controller", body: .object(["threadId": .string(controller)]))
            let draftKey = model.scope + "\nnew", sent = text
            if await model.write(path: "/api/threads", target: "new", body: .object(["prompt": .string(sent)])) {
                if model.drafts[draftKey] == sent { model.drafts[draftKey] = ""; model.saveDrafts() }
                dismiss()
            }
        } catch { failure = error.localizedDescription }
    }
}
struct ConversationMenu: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var jobs = false
    @State private var metadata = false
    @State private var sideChats = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    Paper {
                        Button { sideChats = true } label: { SettingRow(icon: "bubble.left.and.bubble.right", title: "临时聊天", chevron: true) }
                        Divider().padding(.leading, 60)
                        Button { metadata = true } label: { SettingRow(icon: "info.circle", title: "会话信息", chevron: true) }
                        Divider().padding(.leading, 60)
                        Button { jobs = true } label: { SettingRow(icon: "clock", title: "请求记录", chevron: true) }
                    }
                }.padding(20)
            }.background(Design.background).navigationTitle("会话操作").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .sheet(isPresented: $jobs) { RequestLogView() }
                .sheet(isPresented: $sideChats) { SideChatsView() }
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
                            Button("我已在 Codex App 核对结果") { confirmedJob = record }.disabled(!model.canWrite)
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
