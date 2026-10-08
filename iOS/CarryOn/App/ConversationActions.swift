import SwiftUI
import CarryOnCore
import ExyteChat
import PhotosUI

func supportsOperation(_ action: String, in snapshot: JSONValue) -> Bool {
    snapshot["controls"]["supportedOperations"].array.contains(.string(action))
}

struct NewConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var projects: [Record] = []
    @State private var project = ""
    @State private var selecting = false
    private enum CreationPanel: Identifiable {
        case model(String), configuration(String)
        var id: String { switch self { case .model(let scope): "model:" + scope; case .configuration(let scope): "configuration:" + scope } }
    }
    @State private var creationPanel: CreationPanel?
    @State private var creationModels: [JSONValue]?
    @State private var creationModelScope = ""
    @State private var creationModelVersion = UUID()
    @State private var modelCatalogFailure: String?
    @State private var choosingWorkspace = false
    @State private var choosingSkills = false
    @State private var choosingMentions = false
    private var creationSettings: JSONValue { model.draftStore.settings[draftKey] ?? .null }
    private func settingsBinding(scope: String) -> Binding<JSONValue> {
        let key = scope + "\nnew"
        return Binding(get: { model.draftStore.settings[key] ?? .null }, set: { model.draftStore.settings[key] = $0; model.draftStore.save() })
    }
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
        let key = draftKey
        return Binding(get: { model.draftStore.texts[key] ?? "" }, set: { model.draftStore.texts[key] = $0; model.draftStore.save() })
    }
    private var references: [ComposerReference] { model.draftStore.skills[draftKey] ?? [] }
    private var referenceBinding: Binding<[ComposerReference]> {
        let key = draftKey
        return Binding(get: { model.draftStore.skills[key] ?? [] }, set: { model.draftStore.skills[key] = $0; model.draftStore.save() })
    }
    private var selectionBinding: Binding<Int> {
        let key = draftKey
        return Binding(get: { model.composerSelections[key] ?? ((model.draftStore.texts[key] ?? "") as NSString).length }, set: { model.composerSelections[key] = $0 })
    }
    private var referenceTarget: ReferencePickerTarget { .creation(scope: model.scope, project: directCreation ? nil : project) }
    private var referencesAvailable: Bool { model.status["supportsCreationReferences"].bool == true && model.canWrite(.create) && (directCreation || projects.contains(where: { $0.id == project })) }
    private var creationSettingsAllowed: Bool {
        let fields = Set(creationSettings.object?.keys.map { $0 } ?? [])
        let supported = Set(model.status["supportedCreationSettings"].array.compactMap(\.string)).union(["model", "effort"])
        if let selected = creationSettings["model"].string, !selected.isEmpty {
            guard creationModelScope == model.scope, let choice = creationModels?.first(where: { $0["id"].text == selected }),
                  choice["efforts"].array.contains(creationSettings["effort"]) else { return false }
        }
        guard fields.isSubset(of: supported), let capabilities = WorkspaceCapability.request(path: "/api/threads", body: .object(["settings": creationSettings])) else { return false }
        return capabilities.allSatisfy(model.allows)
    }
    @State private var failure: String?
    @State private var loading = false
    @State private var presentationActive = false
    @State private var offset = 0
    @State private var hasMore = true
    @State private var loadVersion = UUID()
    var body: some View {
        NavigationStack {
            ChatView(messages: [], didSendMessage: { _ in }, inputViewBuilder: { _ in
                CarryOnChatComposer(text: draftBinding, skills: referenceBinding, selection: selectionBinding, disabled: !model.canWrite(.create) || !creationSettingsAllowed || (!directCreation && !projects.contains(where: { $0.id == project })) || loading || loadingPhotos,
                                    draftEditable: !loading && !loadingPhotos, hasImages: !images.isEmpty, submitting: loading, placeholder: "询问 CarryOn",
                                    send: { Task { await create() } }) {
                    Menu {
                        PhotosPicker(selection: $photos, maxSelectionCount: max(1, 3 - images.count), matching: .images) { Label("添加图片", systemImage: "photo") }.disabled(images.count >= 3)
                        Button { choosingSkills = true } label: { Label("技能", systemImage: "bolt") }.disabled(!referencesAvailable)
                        Button { choosingMentions = true } label: { Label("应用与插件", systemImage: "at") }.disabled(!referencesAvailable)
                    } label: { Image(systemName: "plus").offset(x: 4).frame(width: 44, height: 44) }
                        .disabled(loading || loadingPhotos).accessibilityLabel("添加附件")
                    if !model.status["supportedCreationSettings"].array.isEmpty {
                        Button { creationPanel = .configuration(model.scope) } label: {
                            Image(systemName: "gearshape").offset(x: -4).frame(width: 44, height: 44)
                        }.disabled(loading || loadingPhotos || !model.canWrite(.create) || !model.canWrite(.edit)).accessibilityLabel("新会话配置")
                    }
                    Spacer(minLength: 4)
                    Button { creationPanel = .model(model.scope) } label: {
                        HStack(spacing: 5) { Text(ModelPresentation.name(creationSettings["model"].string ?? "默认模型", catalog: model.cachedValue("/api/models"))).lineLimit(1); Text(ModelPresentation.effort(creationSettings["effort"].text)).foregroundStyle(Design.secondary) }.font(.subheadline).frame(minHeight: 44)
                    }.accessibilityLabel("模型与思考强度")
                }.id(draftKey)
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
                    if creationSettings["model"] != .null && !creationSettingsAllowed {
                        Button { creationPanel = .model(model.scope) } label: {
                            Text(modelCatalogFailure ?? (creationModels == nil ? "正在核对模型…" : "模型或配置已不可用，请重新选择"))
                                .font(.caption).foregroundStyle(Design.secondary)
                        }.disabled(creationModels == nil && modelCatalogFailure == nil)
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
                .onAppear { presentationActive = true }.onDisappear { presentationActive = false }
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .task(id: model.scope) { projects = []; photos = []; failure = nil; creationPanel = nil; project = model.selectedProject?.id ?? ""; creationModelVersion = UUID(); creationModels = nil; modelCatalogFailure = nil; async let projectLoad: Void = loadProjects(reset: true); async let modelLoad: Void = loadCreationModels(); _ = await (projectLoad, modelLoad) }
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
                .sheet(isPresented: $choosingSkills) { SkillsPickerView(target: referenceTarget) }
                .sheet(isPresented: $choosingMentions) { SkillsPickerView(target: referenceTarget, mentions: true) }
                .onChange(of: project) { _, _ in choosingSkills = false; choosingMentions = false }
                .onChange(of: model.scope) { _, _ in choosingSkills = false; choosingMentions = false }
                .sheet(item: $creationPanel, onDismiss: { Task { await loadCreationModels() } }) { panel in
                    switch panel {
                    case .model(let scope): CreationModelPicker(selection: settingsBinding(scope: scope), scope: scope)
                    case .configuration(let scope): CreationConfigurationView(selection: settingsBinding(scope: scope), scope: scope)
                    }
                }
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
    private func loadCreationModels() async {
        guard !Task.isCancelled else { return }
        let scope = model.scope, version = UUID()
        creationModelVersion = version; creationModels = nil; modelCatalogFailure = nil
        do {
            let catalog = try await model.cachedDeviceRequest("/api/models", maxAge: 0)
            guard !Task.isCancelled, scope == model.scope, creationModelVersion == version else { return }
            guard case .array(let choices) = catalog["models"] else { throw APIError("模型目录格式不正确") }
            creationModels = choices; creationModelScope = scope; modelCatalogFailure = nil
        } catch {
            guard !Task.isCancelled, scope == model.scope, creationModelVersion == version else { return }
            creationModels = nil; modelCatalogFailure = "无法核对模型，请重新选择 · " + error.localizedDescription
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
        guard !loading, !loadingPhotos, model.canWrite(.create), creationSettingsAllowed, directCreation || projects.contains(where: { $0.id == project }) else { return }
        guard references.isEmpty || referencesAvailable else { failure = "当前工作区暂不支持引用，请恢复连接或移除引用后重试"; return }
        loading = true; defer { loading = false }
        let capturedScope = model.scope
        var createdID: String?
        let draftKey = self.draftKey, sent = text, sentImages = images, sentReferences = references
        var fields: [String: JSONValue] = ["prompt": .string(sent.replacingOccurrences(of: ComposerDocument.marker, with: "")),
            "skills": .array(sentReferences.filter { !$0.isMention }.map(\.value)), "mentions": .array(sentReferences.filter(\.isMention).map(\.value))]
        if creationSettings != .null { fields["settings"] = creationSettings }
        if !sentImages.isEmpty { fields["images"] = .array(sentImages.map(JSONValue.string)) }
        if !directCreation { fields["projectId"] = .string(project) }
        if await model.write(path: "/api/threads", target: "new:" + project, body: .object(fields), onCompletion: { job in createdID = job["createdThreadId"].string }) {
            guard capturedScope == model.scope, presentationActive else { return }
            if model.draftStore.texts[draftKey] == sent && (model.draftStore.skills[draftKey] ?? []) == sentReferences { model.draftStore.texts[draftKey] = ""; model.draftStore.skills[draftKey] = []; model.composerSelections[draftKey] = 0; model.draftStore.save() }
            if model.draftStore.images[draftKey] == sentImages { model.draftStore.images[draftKey] = []; model.draftStore.save() }
            dismiss()
            let title = ComposerDocument(text: sent, skills: sentReferences).displayText
            if let createdID, let record = try? Record(.object(["id": .string(createdID), "title": .string(title.isEmpty ? "新建会话" : title)])) { model.open(record) }
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
    private struct ArchiveTarget: Identifiable { let thread: Record; let scope: String; var id: String { scope + thread.id } }
    @State private var archiveTarget: ArchiveTarget?
    @State private var renameTarget: ArchiveTarget?
    @State private var sectionTarget: ArchiveTarget?
    @State private var terminalTarget: ArchiveTarget?
    @State private var skillTarget: ArchiveTarget?
    @State private var pluginTarget: ArchiveTarget?
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
                        if model.status["supportsPluginManagement"].bool == true {
                            Button { if let thread = model.selectedThread { pluginTarget = ArchiveTarget(thread: thread, scope: model.scope) } } label: { SettingRow(icon: "square.grid.2x2", title: "插件", chevron: true) }
                            Divider().padding(.leading, 60)
                        }
                        if model.history["controls"]["supportsSkills"].bool == true, model.canInteract {
                            Button { if let thread = model.selectedThread { skillTarget = ArchiveTarget(thread: thread, scope: model.scope) } } label: { SettingRow(icon: "cube", title: "管理技能", chevron: true) }
                            Divider().padding(.leading, 60)
                        }
                        if model.history["controls"]["supportsBackgroundTerminals"].bool == true, model.canInteract {
                            Button { if let thread = model.selectedThread { terminalTarget = ArchiveTarget(thread: thread, scope: model.scope) } } label: { SettingRow(icon: "terminal", title: "后台终端", chevron: true) }
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
                        if model.status["supportsThreadSections"].bool == true {
                            Button { if let thread = model.selectedThread { sectionTarget = ArchiveTarget(thread: thread, scope: model.scope) } } label: { SettingRow(icon: "pin", title: "移动到分组", chevron: true) }
                                .disabled(!model.canWrite(.edit) || model.writing)
                            Divider().padding(.leading, 60)
                        }
                        if supportsOperation("rename", in: model.history) {
                            Button { if let thread = model.selectedThread { renameTarget = ArchiveTarget(thread: thread, scope: model.scope) } } label: { SettingRow(icon: "pencil", title: "重命名", chevron: true) }
                                .disabled(!model.canInteract(.edit) || model.writing)
                            Divider().padding(.leading, 60)
                        }
                        if supportsOperation("archive", in: model.history) {
                            Button { if let thread = model.selectedThread { archiveTarget = ArchiveTarget(thread: thread, scope: model.scope) } } label: { SettingRow(icon: "archivebox", title: "归档会话", chevron: true) }
                                .disabled(!model.canInteract(.edit) || model.state != "idle" || model.writing)
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
            .sheet(item: $pluginTarget) { target in PluginManagementView(thread: target.thread, scope: target.scope) }
            .sheet(item: $skillTarget) { target in SkillManagementView(thread: target.thread, scope: target.scope) }
            .sheet(item: $terminalTarget) { target in BackgroundTerminalsView(thread: target.thread, scope: target.scope) }
            .sheet(item: $sectionTarget) { target in SectionConversationView(thread: target.thread, scope: target.scope) }
            .sheet(item: $renameTarget) { target in
                RenameConversationView(thread: target.thread, scope: target.scope)
            }
            .sheet(item: $archiveTarget) { target in
                ArchiveActionView(thread: target.thread, scope: target.scope, restoring: false) { dismiss() }
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
