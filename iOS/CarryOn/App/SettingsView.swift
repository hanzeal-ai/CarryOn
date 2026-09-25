import SwiftUI
import UserNotifications
import CarryOnCore

struct SettingsView: View {
    @AppStorage("carryon.showInactiveConversations") private var showInactiveConversations = false
    @Environment(AppModel.self) private var model
    @State private var switcher = false
    @State private var scanning = false
    @State private var links = false
    @State private var notifications = false
    @State private var logout = false
    @State private var logs = false
    @State private var password = false
    @State private var updates = false
    private var standby: JSONValue { model.cachedValue("/api/standby") }
    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                Paper {
                    VStack(spacing: 12) {
                        Image(systemName: "laptopcomputer").font(.system(size: 40, weight: .ultraLight)).foregroundStyle(Design.secondary).padding(.top, 8)
                        HStack(spacing: 5) { Text(model.device?.title ?? "选择工作区").font(.system(size: 18, weight: .semibold)); Button { switcher = true } label: { Image(systemName: "arrow.left.arrow.right").frame(width: 44, height: 44) }.accessibilityLabel("切换工作区") }
                        Label(model.connectionLabel, systemImage: "circle.fill").font(.caption).foregroundStyle(model.connected ? Design.green : Design.secondary)
                    }.padding(12).frame(maxWidth: .infinity)
                    SettingRow(icon: "waveform.path", title: "远程待机", value: standby["supported"].bool == false ? "不支持" : standby["effective"].bool == true ? "已开启" : standby["enabled"].bool == false ? "未开启" : "状态未知")
                    Divider().padding(.leading, 60)
                    SettingRow(icon: "lock", title: "远程控制", value: model.connected ? (model.status["remoteControl"].bool == true ? "已允许" : "只读") : "状态未知")

                    Divider().padding(.leading, 60)
                    Button { scanning = true } label: { SettingRow(icon: "qrcode.viewfinder", title: "扫码绑定工作区", chevron: true) }
                }
                Paper {
                    HStack { Text("Codex 剩余额度").font(.body); Spacer(); CodexUsageView().id(model.scope) }.padding(16)
                }.padding(.top, 16)
                Paper {
                    NavigationLink {
                        settingsPage("账户与配对") {
                            Button { password = true } label: { SettingRow(icon: "lock", title: "修改密码", chevron: true) }
                            Divider().padding(.leading, 60)
                            Button { links = true } label: { SettingRow(icon: "link", title: "连接申请", chevron: true, badgeCount: model.requests.count) }
                        }
                    } label: { SettingRow(icon: "person.crop.circle", title: "账户与配对", chevron: true, badgeCount: model.requests.count) }
                    Divider().padding(.leading, 60)
                    NavigationLink {
                        settingsPage("偏好设置") {
                            VStack(alignment: .leading, spacing: 8) {
                                Toggle("显示不活跃会话", isOn: $showInactiveConversations)
                                Text("开启后显示全部会话；未在桌面 Codex 加载的会话只能查看历史。")
                                    .font(.caption).foregroundStyle(Design.secondary)
                            }.padding(16)
                            Divider().padding(.leading, 60)
                            Button { notifications = true } label: { SettingRow(icon: "bell", title: "消息通知", chevron: true) }
                        }
                    } label: { SettingRow(icon: "slider.horizontal.3", title: "偏好设置", chevron: true) }
                    Divider().padding(.leading, 60)
                    NavigationLink {
                        settingsPage("关于") {
                            Button { logs = true } label: { SettingRow(icon: "doc.text", title: "运行日志", chevron: true) }
                            Divider().padding(.leading, 60)
                            Button { updates = true } label: { SettingRow(icon: "bubble", title: "CarryOn", value: model.appUpdater.currentVersion, chevron: true, imageName: "CarryOnLogo") }
                        }
                    } label: { SettingRow(icon: "info.circle", title: "关于", value: model.appUpdater.currentVersion, chevron: true) }
                }.padding(.top, 16)
                Button(role: .destructive) { logout = true } label: {
                    Text("退出登录").font(.system(size: 15))
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .contentShape(Rectangle())
                }.buttonStyle(.plain).foregroundStyle(.red)
                    .background(Design.surface, in: RoundedRectangle(cornerRadius: 16)).padding(.top, 22)
            }.padding(20)
        }.scrollBounceBehavior(.basedOnSize)
        .task(id: model.scope) { do { _ = try await model.cachedDeviceRequest("/api/standby") } catch { model.report(error, operation: "读取待机状态", blocking: false) } }
        .sheet(isPresented: $switcher) { WorkspaceSwitcher() }
        .sheet(isPresented: $scanning) { WorkspaceBindingView() }
        .sheet(isPresented: $links) { NavigationStack { ScrollView { WorkspaceBindingRequests().padding(20) }.navigationTitle("连接申请") } }
        .sheet(isPresented: $password) { ChangePasswordView() }
        .sheet(isPresented: $notifications) { NotificationPreferencesView() }
        .sheet(isPresented: $updates) { AppUpdateView(updater: model.appUpdater) }
        .sheet(isPresented: $logs) { RuntimeLogView() }
        .confirmationDialog("退出登录？", isPresented: $logout, titleVisibility: .visible) { Button("退出登录", role: .destructive) { Task { await model.logout() } } }

    }
    private func settingsPage<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        ScrollView { Paper(content: content).padding(20) }
            .background(Design.background).navigationTitle(title).navigationBarTitleDisplayMode(.inline)
    }

}
struct NotificationPreferencesView: View {
    @EnvironmentObject private var push: PushNotifications
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var pushStatus = "正在读取系统通知状态…"
    @State private var systemStatus = ""
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
                        VStack(alignment: .leading, spacing: 8) {
                            Text("系统通知").font(.headline)
                            Text(systemStatus).font(.subheadline)
                            Text(pushStatus).font(.caption).foregroundStyle(Design.secondary)
                            Text(push.registrationError.map { "设备推送注册失败：" + $0 } ?? (push.token == nil ? "设备推送尚未完成注册" : "设备已取得推送令牌"))
                                .font(.caption).foregroundStyle(push.registrationError == nil ? Design.secondary : .red)
                            Button("前往系统通知设置") {
                                if let url = URL(string: UIApplication.openNotificationSettingsURLString) { UIApplication.shared.open(url) }
                            }.frame(minHeight: 44)
                        }
                    }
                }.padding(20)
            }.task(id: model.scope + String(scenePhase == .active)) {
                guard scenePhase == .active else { return }
                let scope = model.scope
                let settings = await UNUserNotificationCenter.current().notificationSettings()
                guard !Task.isCancelled, scope == model.scope else { return }
                switch settings.authorizationStatus {
                case .authorized: systemStatus = "手机通知权限已开启"
                case .provisional, .ephemeral: systemStatus = "手机允许静默或临时通知"
                case .denied: systemStatus = "手机通知权限已关闭"
                default: systemStatus = "尚未授权手机通知"
                }
                do {
                    let value = try await model.console("push")
                    guard !Task.isCancelled, scope == model.scope else { return }
                    pushStatus = value["enabled"].bool == true ? "服务端推送已开启，实际送达还取决于设备注册与通知设置。" : "服务端暂未开启系统推送，仍可在动态中查看消息。"
                } catch { guard !Task.isCancelled, scope == model.scope else { return }; pushStatus = "暂时无法确认服务端推送状态，可稍后重新打开查看。" }
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
