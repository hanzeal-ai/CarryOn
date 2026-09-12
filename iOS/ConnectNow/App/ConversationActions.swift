import SwiftUI
import ConnectNowCore

struct NewConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var controllers: [Record] = []
    @State private var controller = ""
    @State private var selecting = false
    @State private var text = ""
    @State private var failure: String?
    @State private var loading = false
    @State private var offset = 0
    @State private var hasMore = true
    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        SectionCaption(title: "控制会话")
                        Paper {
                            Button { selecting = true } label: { SettingRow(icon: "bubble", title: controllers.first(where: { $0.id == controller })?.title ?? "选择控制会话", chevron: true) }
                        }
                        Text("通过电脑端已打开的控制会话创建新会话。").font(.caption).foregroundStyle(Design.secondary)
                        if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                    }.padding(20)
                }
                Composer(text: $text, disabled: !model.canWrite || controller.isEmpty || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || loading, send: { Task { await create() } }) {
                    Image(systemName: "plus").frame(width: 44, height: 44).opacity(0.3).accessibilityLabel("新建会话暂不支持图片")
                }
            }.background(Design.background).navigationTitle("新建会话").navigationBarTitleDisplayMode(.inline)
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
            if await model.write(path: "/api/threads", target: "new", body: .object(["prompt": .string(text)])) { dismiss() }
        } catch { failure = error.localizedDescription }
    }
}
struct ConversationMenu: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var edit = false
    @State private var compact = false
    @State private var settings = false
    @State private var jobs = false
    @State private var metadata = false
    @State private var sideChats = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    Paper {
                        Button { edit = true } label: { SettingRow(icon: "pencil", title: "编辑最后一轮", chevron: true) }.disabled(!model.canWrite || model.state != "idle" || model.history["controls"]["lastUserText"].text.isEmpty)
                        Divider().padding(.leading, 60)
                        Button { compact = true } label: { SettingRow(icon: "arrow.down.right.and.arrow.up.left", title: "压缩上下文", chevron: true) }.disabled(!model.canWrite || model.state != "idle")
                    }
                    Paper {
                        Button { settings = true } label: { SettingRow(icon: "slider.horizontal.3", title: "高级设置", chevron: true) }.disabled(!model.canWrite || !["idle", "active"].contains(model.history["runtime"]["type"].text))
                        Divider().padding(.leading, 60)
                        Button { sideChats = true } label: { SettingRow(icon: "bubble.left.and.bubble.right", title: "临时聊天", chevron: true) }
                        Divider().padding(.leading, 60)
                        Button { metadata = true } label: { SettingRow(icon: "info.circle", title: "会话信息", chevron: true) }
                        Divider().padding(.leading, 60)
                        Button { jobs = true } label: { SettingRow(icon: "clock", title: "请求记录", chevron: true) }
                    }
                }.padding(20)
            }.background(Design.background).navigationTitle("会话操作").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .sheet(isPresented: $edit) { EditConversationView() }
                .sheet(isPresented: $settings) { AdvancedSettingsView() }
                .sheet(isPresented: $jobs) { RequestLogView() }
                .sheet(isPresented: $sideChats) { SideChatsView() }
                .sheet(isPresented: $metadata) { StructuredDetail(title: "会话信息", value: model.history["metadata"]) }
                .alert("压缩此会话的上下文？", isPresented: $compact) {
                    Button("取消", role: .cancel) {}
                    Button("压缩") { Task { if await model.operation("compact") { dismiss() } } }
                }
        }.presentationDetents([.medium, .large])
    }
}
struct EditConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var turn: JSONValue = .null
    @State private var confirm = false
    var body: some View {
        NavigationStack {
            VStack {
                Spacer()
                Composer(text: $text, disabled: !model.canWrite || model.state != "idle" || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, send: { confirm = true }) {
                    Image(systemName: "plus").frame(width: 44, height: 44).opacity(0.3).accessibilityLabel("编辑暂不支持图片")
                }
            }.background(Design.background).navigationTitle("编辑最后一轮").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .onAppear { text = model.history["controls"]["lastUserText"].text; turn = model.history["controls"]["lastTurnId"] }
                .alert("替换并重新执行？", isPresented: $confirm) {
                    Button("取消", role: .cancel) {}
                    Button("替换并重新执行", role: .destructive) { Task { if await model.operation("edit", fields: ["turnId": turn, "prompt": .string(text), "confirmed": .bool(true)]) { dismiss() } } }
                } message: { Text("这会替换最后一轮用户输入及其后续结果，并重新执行。") }
        }
    }
}
struct AdvancedSettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var proposed: JSONValue?
    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 15) {
                Text("填写需要修改的字段；未填写的设置保持不变。权限、沙箱和工作目录的更改会影响后续任务。").font(.caption).foregroundStyle(Design.secondary)
                TextEditor(text: $text).font(.system(.caption, design: .monospaced)).autocorrectionDisabled().textInputAutocapitalization(.never).padding(8).background(.white, in: RoundedRectangle(cornerRadius: 13))
            }.padding(20).background(Design.background).navigationTitle("高级设置").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button("应用") {
                        do { let value = try JSONDecoder().decode(JSONValue.self, from: Data(text.utf8)); guard value.object != nil else { throw APIError("设置必须是 JSON 对象") }; proposed = value } catch { model.report(error) }
                    }.disabled(!model.canWrite) }
                }.onAppear {
                    var value = model.history["controls"]["settings"].object ?? [:]
                    if value["permissions"] != nil && value["permissions"] != .null || value["activePermissionProfile"] != nil && value["activePermissionProfile"] != .null { value.removeValue(forKey: "sandboxPolicy") }
                    text = JSONValue.object(value).formatted
                }.alert("应用这些设置到后续任务？", isPresented: Binding(get: { proposed != nil }, set: { if !$0 { proposed = nil } })) {
                    Button("取消", role: .cancel) { proposed = nil }
                    Button("应用") { if let value = proposed { Task { if await model.operation("settings", fields: ["settings": value]) { dismiss() } } }; proposed = nil }
                } message: { Text(proposed?.formatted ?? "") }
        }
    }
}
struct StructuredDetail: View {
    let title: String
    let value: JSONValue
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack { ScrollView { Text(value.formatted).font(.system(.caption, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(20) }.navigationTitle(title).navigationBarTitleDisplayMode(.inline).toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } } }
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
struct SideChatsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var chats: [Record] = []
    @State private var detail: JSONValue?
    @State private var failure: String?
    @State private var loading = true
    @State private var readingID: String?
    var body: some View {
        NavigationStack {
            List {
                if let failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load() } }) }
                ForEach(chats) { chat in Button { Task { await read(chat.id) } } label: { HStack { Text(chat.title); Spacer(); if readingID == chat.id { ProgressView() } } }.disabled(readingID != nil) }
                if chats.isEmpty && failure == nil { BlankState(text: loading ? "正在查找临时聊天…" : "暂无临时聊天", loading: loading, symbol: "bubble.left.and.bubble.right") }
            }.navigationTitle("临时聊天 · 只读").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .task(id: model.scope) { await load() }
                .sheet(isPresented: Binding(get: { detail != nil }, set: { if !$0 { detail = nil } })) { StructuredDetail(title: "临时聊天 · 只读", value: detail ?? .null) }
        }
    }
    private func load() async {
        guard let parent = model.selectedThread?.id else { loading = false; return }
        loading = true; failure = nil
        defer { loading = false }
        do {
            repeat {
                let value = try await model.deviceRequest("/api/side-chats?parentId=" + ConsoleAddress.component(parent))
                guard !Task.isCancelled, parent == model.selectedThread?.id else { return }
                chats = try value["chats"].array.map(Record.init)
                if value["scanning"].bool != true { break }
                try await Task.sleep(for: .seconds(1))
            } while !Task.isCancelled
        } catch { if !Task.isCancelled { failure = error.localizedDescription } }
    }
    private func read(_ id: String) async {
        guard let parent = model.selectedThread?.id, readingID == nil else { return }
        readingID = id; failure = nil; defer { readingID = nil }
        do { detail = try await model.deviceRequest("/api/side-chats/\(ConsoleAddress.component(id))/history?parentId=" + ConsoleAddress.component(parent)) } catch { failure = error.localizedDescription }
    }
}
