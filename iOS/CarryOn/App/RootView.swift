import SwiftUI
import CarryOnCore

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var tab = 0
    @State private var projectList = RecordListState()
    @State private var threadList = RecordListState()
    @State private var activityList = RecordListState()
    @State private var homeLoader = WorkspaceHomeLoader()
    @State private var homeNavigation = HomeNavigationState()
    @State private var menuOpen = false
    @State private var menuDrag: CGFloat = 0
    var body: some View {
        @Bindable var model = model
        Group {
            if !model.restoringLogin && model.restorationError == nil && !model.authenticated { LoginView() }
            else if !model.authenticated { StartupView() }
            else if model.devices.isEmpty { WorkspaceConnectionHelp() }
            else {
              GeometryReader { geometry in
                let menuWidth = geometry.size.width / 2
                let offset = min(menuWidth, max(0, (menuOpen ? menuWidth : 0) + menuDrag))
                let progress = menuWidth > 0 ? offset / menuWidth : 0
                ZStack(alignment: .leading) {
                    homeMenu.frame(width: menuWidth)
                        .accessibilityHidden(!menuOpen)
                        .allowsHitTesting(menuOpen)
                    mainPage
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .accessibilityHidden(menuOpen)
                        .overlay {
                            if menuOpen {
                                Color.clear.contentShape(Rectangle())
                                    .onTapGesture { setMenuOpen(false) }
                                    .accessibilityHidden(true)
                            }
                        }
                        .clipShape(RoundedRectangle(cornerRadius: 24 * progress, style: .continuous))
                        .overlay {
                            RoundedRectangle(cornerRadius: 24 * progress, style: .continuous)
                                .strokeBorder(Design.border.opacity(progress), lineWidth: 1)
                                .allowsHitTesting(false)
                        }
                        .shadow(color: .black.opacity(0.12 * progress), radius: 18 * progress, x: -6 * progress)
                        .offset(x: offset)
                }
                .background(Design.background)
                .clipped()
                .background(HomeMenuPanGesture(
                    enabled: model.selectedProject == nil && model.selectedThread == nil,
                    menuOpen: menuOpen,
                    changed: { menuDrag = $0 },
                    ended: { translation, velocity, cancelled in
                        withAnimation(reduceMotion ? nil : .interactiveSpring(response: 0.32, dampingFraction: 0.88)) {
                            if !cancelled {
                                let projected = (menuOpen ? menuWidth : 0) + translation + velocity * 0.15
                                setMenuOpen(projected > menuWidth / 2)
                            }
                            menuDrag = 0
                        }
                    }
                ))
                .animation(reduceMotion ? nil : .interactiveSpring(response: 0.32, dampingFraction: 0.88), value: menuOpen)
              }
            }
        }
        .onChange(of: model.scope + String(model.authenticated)) { _, _ in
            projectList.reset(); threadList.reset(); activityList.reset()
            menuOpen = false
            menuDrag = 0
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
    private var mainPage: some View {
        NavigationStack {
            Group {
                switch tab {
                case 1: ActivityView(listState: activityList)
                case 2: SettingsView()
                default: ProjectsView(navigation: homeNavigation, listState: projectList, threadListState: threadList, homeLoader: homeLoader)
                }
            }.id(model.selectedDevice)
                .frame(maxWidth: .infinity, minHeight: 0, maxHeight: .infinity)
                .background(Design.canvas)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button { setMenuOpen(true) } label: {
                            VStack(alignment: .leading, spacing: 5) {
                                Capsule().fill(Design.ink).frame(width: 18, height: 1.5)
                                Capsule().fill(Design.ink).frame(width: 12, height: 1.5)
                            }.frame(width: 44, height: 44)
                        }.accessibilityLabel("导航菜单")
                    }
                }
                .navigationDestination(isPresented: Binding(get: { (model.selectedProject == nil || tab != 0) && model.selectedThread != nil }, set: { if !$0 { model.closeThread() } })) {
                    if let thread = model.selectedThread { ConversationView(thread: thread).id(model.scope + thread.id) }
                }
        }
    }

    private var homeMenu: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("CarryOn").font(.headline)
                    Spacer(minLength: 0)
                    Button { setMenuOpen(false) } label: {
                        Image(systemName: "xmark").frame(width: 44, height: 44)
                    }.accessibilityLabel("关闭菜单")
                }.padding(.bottom, 12)
                menuItem("会话", symbol: "bubble", selected: tab == 0) { tab = 0 }
                menuItem(model.activityBadgeCount > 0 ? "动态（\(model.activityBadgeCount)）" : "动态", symbol: "clock.arrow.circlepath", selected: tab == 1) { tab = 1 }
                menuItem("设置", symbol: "gearshape", selected: tab == 2) { tab = 2 }
                Divider().padding(.vertical, 12)
                menuItem("新建会话", symbol: "square.and.pencil") { tab = 0; homeNavigation.creating = true }
                    .disabled(!model.canWrite(.create))
                menuItem("切换工作区", symbol: "desktopcomputer") { tab = 0; homeNavigation.choosingWorkspace = true }
                menuItem("全部项目", symbol: "folder") { tab = 0; homeNavigation.browsingProjects = true }
                if model.status["supportsThreadSections"].bool == true {
                    menuItem("分组", symbol: "folder") { tab = 0; homeNavigation.browsingSections = true }
                }
                menuItem("已归档", symbol: "archivebox") { tab = 0; homeNavigation.browsingArchives = true }
                menuItem("搜索会话", symbol: "magnifyingglass") { tab = 0; homeNavigation.browsingThreads = true }
                if model.status["supportsFullTextSearch"].bool == true {
                    menuItem("搜索会话内容", symbol: "text.magnifyingglass") { tab = 0; homeNavigation.searchingContent = true }
                }
            }.padding(.horizontal, 12).padding(.vertical, 16)
        }
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Design.background)
        .accessibilityAction(.escape) { setMenuOpen(false) }
    }

    private func menuItem(_ title: String, symbol: String, selected: Bool = false, action: @escaping () -> Void) -> some View {
        Button {
            setMenuOpen(false)
            action()
        } label: {
            HStack(spacing: 10) {
                Image(systemName: symbol).frame(width: 22)
                Text(title).font(.subheadline).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }.padding(.horizontal, 10).padding(.vertical, 10)
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .background(selected ? Design.border : .clear, in: RoundedRectangle(cornerRadius: 12))
                .contentShape(Rectangle())
        }.buttonStyle(.plain)
            .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func setMenuOpen(_ open: Bool) {
        menuOpen = open
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
