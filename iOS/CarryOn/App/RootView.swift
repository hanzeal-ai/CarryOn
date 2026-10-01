import SwiftUI
import CarryOnCore

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var tab = 0
    @State private var projectList = RecordListState()
    @State private var threadList = RecordListState()
    @State private var activityList = RecordListState()
    @State private var homeLoader = WorkspaceHomeLoader()
    var body: some View {
        @Bindable var model = model
        Group {
            if !model.restoringLogin && model.restorationError == nil && !model.authenticated { LoginView() }
            else if !model.authenticated { StartupView() }
            else if model.devices.isEmpty { WorkspaceConnectionHelp() }
            else {
              NavigationStack {
                VStack(spacing: 0) {
                    Group {
                        switch tab {
                        case 1: ActivityView(listState: activityList)
                        case 2: SettingsView()
                        default: ProjectsView(listState: projectList, threadListState: threadList, homeLoader: homeLoader)
                        }
                    }.id(model.selectedDevice)
                        .frame(maxWidth: .infinity, minHeight: 0, maxHeight: .infinity)
                        .clipped()
                }.background(Design.canvas)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Menu {
                            Button { tab = 0 } label: { Label("会话", systemImage: "bubble") }
                            Button { tab = 1 } label: { Label(model.activityBadgeCount > 0 ? "动态（\(model.activityBadgeCount)）" : "动态", systemImage: "clock.arrow.circlepath") }
                            Button { tab = 2 } label: { Label("设置", systemImage: "gearshape") }
                        } label: { VStack(alignment: .leading, spacing: 5) {
                            Capsule().fill(Design.ink).frame(width: 18, height: 1.5)
                            Capsule().fill(Design.ink).frame(width: 12, height: 1.5)
                        }.frame(width: 28, height: 28) }
                            .accessibilityLabel("导航菜单")
                    }
                }
                .navigationDestination(isPresented: Binding(get: { (model.selectedProject == nil || tab != 0) && model.selectedThread != nil }, set: { if !$0 { model.closeThread() } })) {
                    if let thread = model.selectedThread { ConversationView(thread: thread).id(model.scope + thread.id) }
                }
              }
            }
        }
        .onChange(of: model.scope + String(model.authenticated)) { _, _ in
            projectList.reset(); threadList.reset(); activityList.reset()
        }
        .foregroundStyle(Design.ink)
        .background(ImageLightboxPresenter(image: model.previewImage, isPresented: Binding(
            get: { model.previewImage != nil }, set: { if !$0 { model.previewImage = nil } }
        )).frame(width: 0, height: 0))
        .alert("暂时无法完成", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("知道了", role: .cancel) { model.error = nil }
        } message: { Text(model.error ?? "") }
        .alert("已提交", isPresented: Binding(get: { model.notice != nil }, set: { if !$0 { model.notice = nil } })) {
            Button("好", role: .cancel) { model.notice = nil }
        } message: { Text(model.notice ?? "") }
    }
}

struct StartupView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        VStack(spacing: 20) {
            if let failure = model.restorationError {
                Text("连接失败").font(.headline)
                Text(failure).font(.footnote).foregroundStyle(Design.secondary).multilineTextAlignment(.center)
                Button("重试") { Task { await model.restoreLogin() } }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent)
                Button("返回登录") { model.restorationError = nil }
            } else {
                ProgressView("正在连接…")
            }
        }.padding(28).frame(maxWidth: .infinity, maxHeight: .infinity).background(Design.background)
    }
}
struct LoginView: View {
    @State private var scan = false
    @State private var registering = false
    @State private var confirmation = ""
    @State private var inviteCode = ""
    @Environment(AppModel.self) private var model
    private var canSubmit: Bool {
        !model.busy && !model.addressText.isEmpty
            && !model.username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !model.credential.isEmpty
            && (!registering || (model.credential.count >= 12 && model.credential == confirmation && !inviteCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
    }
    var body: some View {
        @Bindable var model = model
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Image("CarryOnLoginLogo")
                    .resizable().scaledToFit().frame(width: 112, height: 168)
                    .frame(maxWidth: .infinity).padding(.vertical, 8)
                    .accessibilityLabel("CarryOn")

                VStack(alignment: .leading, spacing: 12) {
                    Text("账号").font(.caption).foregroundStyle(Design.secondary)
                    TextField("输入账号", text: $model.username).textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled().padding(15).background(Design.surface, in: RoundedRectangle(cornerRadius: Design.controlCorner))
                    Text("密码").font(.caption).foregroundStyle(Design.secondary)
                    SecureField(registering ? "至少 12 位密码" : "输入密码", text: $model.credential).textContentType(registering ? .newPassword : .password).padding(15).background(Design.surface, in: RoundedRectangle(cornerRadius: Design.controlCorner))
                    if registering {
                        TextField("邀请码", text: $inviteCode).textInputAutocapitalization(.never).autocorrectionDisabled().padding(15).background(Design.surface, in: RoundedRectangle(cornerRadius: Design.controlCorner))
                        SecureField("再次输入密码", text: $confirmation).textContentType(.newPassword).padding(15).background(Design.surface, in: RoundedRectangle(cornerRadius: Design.controlCorner))
                    }
                    Button { Task { await model.login(register: registering, inviteCode: inviteCode) } } label: {
                        HStack { Spacer(); if model.busy { ProgressView().tint(Design.onAccent) } else { Text(registering ? "注册并登录" : "登录").fontWeight(.semibold) }; Spacer() }.frame(minHeight: 50)
                    }.background(Design.ink, in: RoundedRectangle(cornerRadius: Design.controlCorner)).foregroundStyle(Design.onAccent)
                        .disabled(!canSubmit).opacity(canSubmit || model.busy ? 1 : 0.4)
                    Button(registering ? "已有账号？登录" : "创建账号") { registering.toggle(); confirmation = ""; inviteCode = "" }.frame(maxWidth: .infinity, minHeight: 36).disabled(model.busy)
                }
            }.padding(28).frame(maxWidth: 500)
        }.frame(maxWidth: .infinity).background(Design.background).scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 4) {
                Button { scan = true } label: { Label("扫码登录", systemImage: "qrcode.viewfinder").frame(maxWidth: .infinity, minHeight: 44) }.disabled(model.busy)
            }.padding(.horizontal, 28).padding(.top, 8).padding(.bottom, 8)
                .frame(maxWidth: .infinity).background(Design.background)
        }
        .sheet(isPresented: $scan) { QRLoginView() }
    }
}
