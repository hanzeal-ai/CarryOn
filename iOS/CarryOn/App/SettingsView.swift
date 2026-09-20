import SwiftUI
import CarryOnCore

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var switcher = false
    @State private var scanning = false
    @State private var links = false
    @State private var notifications = false
    @State private var logout = false
    @State private var logs = false
    @State private var updates = false
    private var standby: JSONValue { model.cachedValue("/api/standby") }
    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                Paper {
                    VStack(spacing: 12) {
                        Image(systemName: "laptopcomputer").font(.system(size: 58, weight: .ultraLight)).foregroundStyle(Design.secondary).padding(.top, 8)
                        HStack(spacing: 5) { Text(model.device?.title ?? "选择工作区").font(.system(size: 18, weight: .semibold)); Button { switcher = true } label: { Image(systemName: "arrow.left.arrow.right").frame(width: 44, height: 44) }.accessibilityLabel("切换工作区") }
                        Label(model.connectionLabel, systemImage: "circle.fill").font(.caption).foregroundStyle(model.connected ? Design.green : Design.secondary)
                    }.padding(22).frame(maxWidth: .infinity)
                    SettingRow(icon: "waveform.path", title: "远程待机", value: standby["supported"].bool == false ? "不支持" : standby["effective"].bool == true ? "已开启" : standby["enabled"].bool == false ? "未开启" : "状态未知")
                    Divider().padding(.leading, 60)
                    SettingRow(icon: "lock", title: "远程控制", value: model.connected ? (model.status["remoteControl"].bool == true ? "已允许" : "只读") : "状态未知")

                }.overlay(alignment: .topLeading) {
                    Button { scanning = true } label: {
                        Image(systemName: "qrcode.viewfinder")
                            .font(.system(size: 22))
                            .frame(width: 44, height: 44)
                    }.buttonStyle(.plain).accessibilityLabel("扫一扫，绑定工作区").padding(10)
                }.overlay(alignment: .topTrailing) {
                    CodexUsageView().id(model.scope).padding(10)
                }
                SectionCaption(title: "账户与配对")
                Paper {
                    Button { links = true } label: { SettingRow(icon: "link", title: "连接申请", chevron: true, badgeCount: model.requests.count) }

                }
                SectionCaption(title: "通知")
                Paper { Button { notifications = true } label: { SettingRow(icon: "bell", title: "消息通知", chevron: true) } }
                SectionCaption(title: "关于")
                Paper {
                    Button { logs = true } label: { SettingRow(icon: "doc.text", title: "运行日志", chevron: true) }
                    Divider().padding(.leading, 60)
                    Button { updates = true } label: { SettingRow(icon: "bubble", title: "CarryOn", value: model.appUpdater.currentVersion, chevron: true, imageName: "CarryOnLogo") }.accessibilityLabel("CarryOn " + model.appUpdater.currentVersion + "，检查更新")
                }
                Button(role: .destructive) { logout = true } label: {
                    Text("退出登录").font(.system(size: 15))
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .contentShape(Rectangle())
                }.buttonStyle(.plain).foregroundStyle(.red)
                    .background(Design.surface, in: RoundedRectangle(cornerRadius: 16)).padding(.top, 22)
            }.padding(20)
        }
        .task(id: model.scope) { do { _ = try await model.cachedDeviceRequest("/api/standby") } catch { model.report(error, operation: "读取待机状态", blocking: false) } }
        .sheet(isPresented: $switcher) { WorkspaceSwitcher() }
        .sheet(isPresented: $scanning) { WorkspaceBindingView() }
        .sheet(isPresented: $links) { ConnectionRequestsView() }
        .sheet(isPresented: $notifications) { NotificationPreferencesView() }
        .sheet(isPresented: $updates) { AppUpdateView(updater: model.appUpdater) }
        .sheet(isPresented: $logs) { RuntimeLogView() }
        .confirmationDialog("退出登录？", isPresented: $logout, titleVisibility: .visible) { Button("退出登录", role: .destructive) { Task { await model.logout() } } }

    }
}
struct NotificationPreferencesView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var values: [String: Bool] = [:]
    @State private var saving = false
    @State private var loading = true
    @State private var loadVersion = UUID()
    @State private var failure: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if values.isEmpty {
                        if loading { BlankState(text: "正在加载通知设置…", loading: true) }
                        else { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load() } }) }
                    } else {
                        if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                        Paper {
                            ForEach(["message", "done", "failed", "approval"], id: \.self) { key in
                                Toggle(["message": "新消息", "done": "任务完成", "failed": "执行失败", "approval": "需要确认"][key]!, isOn: Binding(get: { values[key] ?? false }, set: { values[key] = $0 })).padding(16)
                                if key != "approval" { Divider().padding(.leading, 16) }
                            }
                        }.disabled(saving)
                        Text("开启的消息类型会显示在动态中。关闭不会删除消息或未读标记。").font(.caption).foregroundStyle(Design.secondary)
                        Text("系统通知还需云端 APNs 配置及 iOS 通知权限。").font(.caption).foregroundStyle(Design.secondary)
                    }
                }.padding(20)
            }.background(Design.background).navigationTitle("消息通知").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button { Task {
                        saving = true; defer { saving = false }
                        do { _ = try await model.deviceRequest("/api/notifications/preferences", body: .object(values.mapValues(JSONValue.bool))); dismiss() } catch { failure = error.localizedDescription; model.report(error, operation: "保存消息通知设置") }
                    } } label: { if saving { ProgressView("保存中…") } else { Text("保存") } }.disabled(values.count != 4 || saving || loading) }
                }.task(id: model.scope) { values = [:]; await load() }
        }
    }
    private func load() async {
        let version = UUID(), scope = model.scope; loadVersion = version
        loading = true; failure = nil
        defer { if loadVersion == version { loading = false } }
        do {
            let result = try await model.deviceRequest("/api/notifications/preferences")
            guard version == loadVersion, scope == model.scope, !Task.isCancelled else { return }
            var next: [String: Bool] = [:]
            for key in ["message", "done", "failed", "approval"] {
                guard let value = result["preferences"][key].bool else { throw APIError("通知偏好格式不正确") }; next[key] = value
            }
            values = next; failure = nil
        } catch { if version == loadVersion && scope == model.scope && !Task.isCancelled { failure = error.localizedDescription; model.report(error, operation: "读取消息通知设置", blocking: false) } }
    }
}
struct ConnectionRequestsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var selected: Record?
    @State private var processing = false
    @State private var clearHistory = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 15) {
                    if model.requests.isEmpty { BlankState(text: "暂无待确认的连接申请") }
                    ForEach(model.requests) { request in
                        Paper {
                            VStack(alignment: .leading, spacing: 12) {
                                Text(request.title).font(.headline)
                                if case .number(let date) = request.value["created"] { Text(Date(timeIntervalSince1970: date), style: .date).font(.caption); Text(Date(timeIntervalSince1970: date), style: .time).font(.caption) }
                                Text(request.value["verification"].text).font(.system(.title2, design: .monospaced)).tracking(3)
                                Text("请与本机显示的确认码核对。确认后默认只读。").font(.caption).foregroundStyle(Design.secondary)
                                HStack {
                                    Button("拒绝", role: .destructive) { Task { await respond(request, approve: false) } }.buttonStyle(.bordered)
                                    Spacer()
                                    Button("确认连接") { selected = request }.buttonStyle(.borderedProminent)
                                }.disabled(processing)
                            }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    HStack {
                        Text("历史申请").font(.caption).foregroundStyle(Design.secondary)
                        Spacer()
                        if !model.requestHistory.isEmpty { Button { clearHistory = true } label: { Image(systemName: "trash").font(.system(size: 16)).frame(width: 44, height: 44) }.foregroundStyle(Design.secondary).accessibilityLabel("清空历史").disabled(processing) }
                    }
                    if let warning = model.requestHistoryError { Text(warning).font(.caption).foregroundStyle(.red) }
                    if model.requestHistory.isEmpty { Text("暂无历史申请").foregroundStyle(Design.secondary) }
                    ForEach(model.requestHistory) { request in
                        Paper {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(request.title).font(.caption).foregroundStyle(Design.secondary)
                                    Spacer()
                                    Text(["approved": "已同意", "rejected": "已拒绝", "expired": "已过期"][request.value["result"].text] ?? "未知")
                                        .font(.caption).foregroundStyle(Design.secondary)
                                }
                                if case .number(let date) = request.value["created"] { Text("申请时间 · " + Date(timeIntervalSince1970: date).formatted()).font(.caption) }
                                if case .number(let date) = request.value["resolvedAt"] { Text("处理时间 · " + Date(timeIntervalSince1970: date).formatted()).font(.caption) }
                            }.foregroundStyle(Design.secondary).padding(18).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }.padding(20)
            }.background(Design.background).navigationTitle("连接申请").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .task { do { try await model.refreshDirectory() } catch { model.report(error, operation: "刷新连接申请", blocking: false) } }
                .alert("清空历史申请？", isPresented: $clearHistory) {
                    Button("取消", role: .cancel) {}
                    Button("清空", role: .destructive) { Task {
                        processing = true; defer { processing = false }
                        do {
                            _ = try await model.console("link/history", method: "DELETE")
                            model.requestHistory = []
                            try await model.refreshDirectory()
                        } catch { model.report(error) }
                    } }
                } message: { Text("仅清空历史记录，待处理申请和已连接设备不受影响。") }
                .refreshable { do { try await model.refreshDirectory() } catch { model.report(error, operation: "刷新连接申请", blocking: false) } }
                .alert("确认设备名称、时间与两端确认码一致？", isPresented: Binding(get: { selected != nil }, set: { if !$0 { selected = nil } })) {
                    Button("取消", role: .cancel) { selected = nil }
                    Button("确认连接") { if let request = selected { Task { await respond(request, approve: true) } }; selected = nil }
                } message: { Text(selected?.value["verification"].text ?? "") }
        }
    }
    private func respond(_ request: Record, approve: Bool) async {
        processing = true; defer { processing = false }
        do {
            _ = try await model.console(approve ? "link/approve" : "link/reject", body: .object(["id": .string(request.id)]))
            try await model.refreshDirectory()
        } catch { model.report(error) }
    }
}
