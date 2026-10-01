import SwiftUI
import CarryOnCore
import ExyteChat
import PhotosUI

func supportsOperation(_ action: String, in snapshot: JSONValue) -> Bool {
    snapshot["controls"]["supportedOperations"] == .null || snapshot["controls"]["supportedOperations"].array.contains(.string(action))
}

struct NewConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var projects: [Record] = []
    @State private var project = ""
    @State private var selecting = false
    @State private var choosingModel = false
    @State private var choosingWorkspace = false
    @State private var creationSettings: JSONValue = .null
    @State private var photos: [PhotosPickerItem] = []
    @State private var loadingPhotos = false
    private var draftKey: String { model.scope + "\nnew" }
    private var images: [String] {
        get { model.draftStore.images[draftKey] ?? [] }
        nonmutating set { model.draftStore.images[draftKey] = newValue; model.draftStore.save() }
    }
    private var directCreation: Bool { model.status["supportsDirectCreation"].bool == true }
    private var text: String { model.draftStore.texts[model.scope + "\nnew"] ?? "" }
    private var draftBinding: Binding<String> {
        Binding(get: { text }, set: { model.draftStore.texts[draftKey] = $0; model.draftStore.save() })
    }
    @State private var failure: String?
    @State private var loading = false
    @State private var offset = 0
    @State private var hasMore = true
    @State private var loadVersion = UUID()
    var body: some View {
        NavigationStack {
            ChatView(messages: [], didSendMessage: { _ in }, inputViewBuilder: { _ in
                CarryOnChatComposer(text: draftBinding, disabled: !model.canWrite(.create) || (!directCreation && !projects.contains(where: { $0.id == project })) || loading || loadingPhotos,
                                    draftEditable: !loading && !loadingPhotos, hasImages: !images.isEmpty, submitting: loading, placeholder: "询问 CarryOn",
                                    send: { Task { await create() } }) {
                    PhotosPicker(selection: $photos, maxSelectionCount: max(1, 3 - images.count), matching: .images) {
                        Image(systemName: "plus").frame(width: 44, height: 44)
                    }.disabled(loading || loadingPhotos || images.count >= 3).accessibilityLabel("添加图片")
                    Spacer(minLength: 4)
                    Button { choosingModel = true } label: {
                        HStack(spacing: 5) { Text(ModelPresentation.name(creationSettings["model"].string ?? "默认模型", catalog: model.cachedValue("/api/models"))).lineLimit(1); Text(ModelPresentation.effort(creationSettings["effort"].text)).foregroundStyle(Design.secondary) }.font(.subheadline).frame(minHeight: 44)
                    }.accessibilityLabel("模型与思考强度")
                }
            })
            .setAvailableInputs([.text])
            .betweenListAndInputViewBuilder {
                VStack(alignment: .leading, spacing: 8) {
                    Button { choosingWorkspace = true } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "desktopcomputer")
                            Text(model.device?.title ?? "工作区").lineLimit(1)
                            Image(systemName: "chevron.up.chevron.down").font(.caption)
                        }.font(.subheadline).foregroundStyle(Design.secondary).frame(minHeight: 44)
                    }.accessibilityLabel("切换工作区")
                    if !directCreation {
                        Button { selecting = true } label: {
                            HStack(spacing: 10) {
                                Image(systemName: "folder")
                                Text(projects.first(where: { $0.id == project })?.title ?? "选择项目").lineLimit(1)
                                Image(systemName: "chevron.up.chevron.down").font(.caption)
                            }.font(.subheadline).foregroundStyle(Design.secondary).frame(minHeight: 44)
                        }
                    }
                    if loadingPhotos { ProgressView("正在处理图片…") }
                    if !images.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 12) {
                                ForEach(Array(images.enumerated()), id: \.offset) { index, url in
                                    DraftImageThumbnail(dataURL: url) {
                                        guard images.indices.contains(index), images[index] == url else { return }
                                        images.remove(at: index)
                                    }.disabled(loading)
                                }
                            }.padding(.vertical, 6)
                        }
                    }
                    if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 24)
            }
            .carryOnChatAppearance()
            .disabled(loading)
            .navigationTitle("新建会话").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .task(id: model.scope) { projects = []; photos = []; failure = nil; creationSettings = .null; choosingModel = false; project = model.selectedProject?.id ?? ""; await loadProjects(reset: true) }
                .task(id: photos) {
                    guard !photos.isEmpty else { return }
                    let scope = model.scope
                    loadingPhotos = true
                    defer { loadingPhotos = false }
                    do {
                        let added = try await conversationPhotos(photos)
                        guard !Task.isCancelled, scope == model.scope else { return }
                        images = Array((images + added).prefix(3)); photos = []
                    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
                }
                .sheet(isPresented: $choosingWorkspace) { WorkspaceSwitcher() }
                .sheet(isPresented: $choosingModel) { CreationModelPicker(selection: $creationSettings, scope: model.scope) }
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
        guard !loading, !loadingPhotos, model.canWrite(.create), directCreation || projects.contains(where: { $0.id == project }) else { return }
        loading = true; defer { loading = false }
        let draftKey = self.draftKey, sent = text, sentImages = images
        var fields: [String: JSONValue] = ["prompt": .string(sent)]
        if creationSettings != .null { fields["settings"] = creationSettings }
        if !sentImages.isEmpty { fields["images"] = .array(sentImages.map(JSONValue.string)) }
        if !directCreation { fields["projectId"] = .string(project) }
        if await model.write(path: "/api/threads", target: "new:" + project, body: .object(fields)) {
            if model.draftStore.texts[draftKey] == sent { model.draftStore.texts[draftKey] = ""; model.draftStore.save() }
            if model.draftStore.images[draftKey] == sentImages { model.draftStore.images[draftKey] = []; model.draftStore.save() }
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
    @State private var forking = false
    @State private var reviewing = false
    @State private var goal = false
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
                        if let thread = model.selectedThread, !model.conversationReadOnly,
                           model.status["supportsSessionLoading"].bool == true,
                           !model.canInteract || model.history["executionBackend"].text == "carryon-owner" {
                            let loaded = model.history["executionBackend"].text == "carryon-owner"
                            Button {
                                Task {
                                    let path = "/api/threads/\(ConsoleAddress.component(thread.id))/session"
                                    if await model.write(path: path, target: thread.id,
                                        body: .object(["action": .string(loaded ? "release" : "load")])) {
                                        model.retryHistory()
                                    }
                                }
                            } label: { SettingRow(icon: "arrow.clockwise", title: loaded ? "释放手机加载的会话" : "加载会话") }
                                .disabled(!model.canWrite(.send) || model.writing)
                            Divider().padding(.leading, 60)
                        }
                        if model.history["controls"]["supportsGoal"].bool == true {
                            Button { goal = true } label: { SettingRow(icon: "target", title: "会话目标", chevron: true) }
                            Divider().padding(.leading, 60)
                        }
                        if model.history["controls"]["supportedOperations"].array.contains(.string("review")) {
                            Button { reviewing = true } label: { SettingRow(icon: "doc.text.magnifyingglass", title: "审查代码", chevron: true) }
                                .disabled(!model.canInteract(.send) || model.state != "idle")
                            Divider().padding(.leading, 60)
                        }
                        if model.history["controls"]["supportedOperations"].array.contains(.string("fork")) {
                            Button { forking = true } label: { SettingRow(icon: "arrow.triangle.branch", title: "分叉会话", chevron: true) }
                                .disabled(!model.canWrite(.create) || model.state != "idle" || model.writing)
                            Divider().padding(.leading, 60)
                        }
                        Button { jobs = true } label: { SettingRow(icon: "clock", title: "请求记录", chevron: true) }
                    }
                }.padding(20)
            }.background(Design.background).navigationTitle("会话操作").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .sheet(isPresented: $forking) {
                if let thread = model.selectedThread {
                    ForkConversationView(thread: thread, scope: model.scope) { dismiss() }
                }
            }
            .sheet(isPresented: $goal) {
                if let thread = model.selectedThread {
                    ConversationGoalView(target: .init(scope: model.scope, threadID: thread.id))
                }
            }
            .sheet(isPresented: $reviewing) {
                if let thread = model.selectedThread {
                    ReviewConversationView(target: .init(scope: model.scope, threadID: thread.id)) { dismiss() }
                }
            }
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
                        if record.value["kind"].text == "quota-reset", record.value["state"].text == "uncertain" {
                            Text("请到“我的”额度详情使用原请求核对并重试").font(.caption)
                        } else if record.value["kind"].text != "quota-reset", ["uncertain", "failed"].contains(record.value["state"].text) {
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
