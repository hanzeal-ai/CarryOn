import SwiftUI
import CarryOnCore

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var tab = 0
    @AppStorage("carryon.projectView") private var projectView = true
    @State private var switcher = false
    var body: some View {
        @Bindable var model = model
        Group {
            if !model.authenticated { LoginView() }
            else {
              NavigationStack {
                VStack(spacing: 0) {
                    if tab != 2 {
                        HStack {
                            Button { switcher = true } label: {
                                Label(model.device?.title ?? "选择工作区", systemImage: "laptopcomputer")
                                Image(systemName: "chevron.down").font(.caption2)
                            }.font(.system(size: 13)).foregroundStyle(Design.secondary)
                            Spacer()
                            HStack(spacing: 4) { Circle().fill(model.connected ? Design.green : Design.secondary).frame(width: 5, height: 5); Text(model.connectionLabel).font(.caption2) }
                        }.padding(.horizontal, 20).frame(minHeight: 50)
                    }
                    Group {
                        switch tab {
                        case 1: ActivityView()
                        case 2: SettingsView()
                        default: ProjectsView()
                        }
                    }.id(model.selectedDevice)
                    HStack(spacing: 3) {
                        tabButton(0, "会话", "bubble")
                        tabButton(1, "动态", "clock.arrow.circlepath")
                        tabButton(2, "我的", "person.crop.circle")
                    }.padding(5).background(.white.opacity(0.95), in: Capsule()).padding(.horizontal, 14).padding(.bottom, 4)
                }.background(Design.background)
                .navigationDestination(isPresented: Binding(get: { (model.selectedProject == nil || tab != 0) && model.selectedThread != nil }, set: { if !$0 { model.closeThread() } })) {
                    if let thread = model.selectedThread { ConversationView(thread: thread).id(model.scope + thread.id) }
                }
              }
            }
        }
        .foregroundStyle(Design.ink)
        .background(KeyboardDismissal())
        .sheet(isPresented: $switcher) { WorkspaceSwitcher() }
        .alert("暂时无法完成", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("知道了", role: .cancel) { model.error = nil }
        } message: { Text(model.error ?? "") }
        .alert("已提交", isPresented: Binding(get: { model.notice != nil }, set: { if !$0 { model.notice = nil } })) {
            Button("好", role: .cancel) { model.notice = nil }
        } message: { Text(model.notice ?? "") }
    }
    private func tabButton(_ index: Int, _ label: String, _ icon: String) -> some View {
        Button {
            if index == 0 && tab == 0 {
                model.selectedProject = nil
                projectView.toggle()
            }
            tab = index
        } label: {
            VStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 22)).overlay(alignment: .topTrailing) {
                    let count = model.activityBadgeCount
                    if index == 1 && count > 0 {
                        Text(count > 99 ? "99+" : "\(count)").font(.system(size: 9, weight: .medium)).foregroundStyle(.white).padding(.horizontal, 4).frame(minWidth: 15, minHeight: 15).background(.red, in: Capsule()).offset(x: 12, y: -6)
                    }
                }
                HStack(spacing: 3) {
                    Text(label)
                    if index == 0 {
                        Image(systemName: "arrow.left.arrow.right")
                    }
                }.font(.system(size: 10))
            }
                .foregroundStyle(tab == index ? Design.ink : Design.secondary)
                .frame(maxWidth: .infinity).frame(minHeight: 54)
                .background(tab == index ? Design.background : .clear, in: Capsule())
        }.accessibilityAddTraits(tab == index ? .isSelected : [])
            .accessibilityValue(index == 0 ? (projectView ? "项目视图" : "会话视图") : "")
            .accessibilityHint(index == 0 ? (tab == 0 ? "再次点击切换项目和会话视图" : "打开会话") : "")
    }
}
struct LoginView: View {
    @State private var scan = false
    @State private var advancedSettings = false
    @State private var registering = false
    @State private var confirmation = ""
    @Environment(AppModel.self) private var model
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
                    TextField("输入账号", text: $model.username).textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled().padding(15).background(.white, in: RoundedRectangle(cornerRadius: 13))
                    Text("密码").font(.caption).foregroundStyle(Design.secondary)
                    SecureField(registering ? "至少 12 位密码" : "输入密码", text: $model.credential).textContentType(registering ? .newPassword : .password).padding(15).background(.white, in: RoundedRectangle(cornerRadius: 13))
                    if registering {
                        SecureField("再次输入密码", text: $confirmation).textContentType(.newPassword).padding(15).background(.white, in: RoundedRectangle(cornerRadius: 13))
                    }
                    Button { Task { await model.login(register: registering) } } label: {
                        HStack { Spacer(); if model.busy { ProgressView().tint(.white) } else { Text(registering ? "注册并登录" : "登录").fontWeight(.semibold) }; Spacer() }.frame(minHeight: 50)
                    }.background(Design.ink, in: RoundedRectangle(cornerRadius: 13)).foregroundStyle(.white)
                        .disabled(model.busy || model.addressText.isEmpty || model.username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.credential.isEmpty || (registering && (model.credential.count < 12 || model.credential != confirmation)))
                    Button(registering ? "已有账号？登录" : "创建账号") { registering.toggle(); confirmation = "" }.frame(maxWidth: .infinity, minHeight: 36).disabled(model.busy)
                    Button { scan = true } label: { Label("扫码登录", systemImage: "qrcode.viewfinder").frame(maxWidth: .infinity, minHeight: 44) }.disabled(model.busy)
                    Button("高级设置") { advancedSettings = true }
                        .font(.footnote).foregroundStyle(Design.secondary)
                        .frame(maxWidth: .infinity, minHeight: 44).disabled(model.busy)
                }
            }.padding(28).frame(maxWidth: 500)
        }.frame(maxWidth: .infinity).background(Design.background).scrollDismissesKeyboard(.interactively)
        .sheet(isPresented: $scan) { QRLoginView() }
        .sheet(isPresented: $advancedSettings) { CloudSettingsView() }
    }
}
