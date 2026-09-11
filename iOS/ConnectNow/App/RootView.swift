import SwiftUI
import ConnectNowCore

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var tab = 0
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
        Button { tab = index } label: {
            VStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 22)).overlay(alignment: .topTrailing) {
                    let count = model.activityBadgeCount
                    if index == 1 && count > 0 {
                        Text(count > 99 ? "99+" : "\(count)").font(.system(size: 9, weight: .medium)).foregroundStyle(.white).padding(.horizontal, 4).frame(minWidth: 15, minHeight: 15).background(.red, in: Capsule()).offset(x: 12, y: -6)
                    }
                }
                Text(label).font(.system(size: 10))
            }
                .foregroundStyle(tab == index ? Design.ink : Design.secondary)
                .frame(maxWidth: .infinity).frame(minHeight: 54)
                .background(tab == index ? Design.background : .clear, in: Capsule())
        }.accessibilityAddTraits(tab == index ? .isSelected : [])
    }
}
struct LoginView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        @Bindable var model = model
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("ConnectNow").font(.system(size: 20, weight: .semibold)).padding(.top, 35)
                Spacer(minLength: 50)
                Image(systemName: "arrow.up.right").font(.system(size: 45, weight: .light))
                Text("查看进展，\n继续对话。").font(.system(size: 36, weight: .semibold)).tracking(-1)
                Text("让工作随你同行。").foregroundStyle(Design.secondary)
                VStack(alignment: .leading, spacing: 12) {
                    Text("云端地址").font(.caption).foregroundStyle(Design.secondary)
                    TextField("https://…", text: $model.addressText).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled().padding(15).background(.white, in: RoundedRectangle(cornerRadius: 13))
                    Text("控制台登录凭证").font(.caption).foregroundStyle(Design.secondary)
                    SecureField("输入登录凭证", text: $model.credential).textContentType(.password).padding(15).background(.white, in: RoundedRectangle(cornerRadius: 13))
                    Button { Task { await model.login() } } label: {
                        HStack { Spacer(); if model.busy { ProgressView().tint(.white) } else { Text("登录").fontWeight(.semibold) }; Spacer() }.frame(minHeight: 50)
                    }.background(Design.ink, in: RoundedRectangle(cornerRadius: 13)).foregroundStyle(.white)
                        .disabled(model.busy || model.addressText.isEmpty || model.credential.isEmpty)
                    Text("登录后选择已登记的电脑。登录凭证与设备配对码用途不同。").font(.caption).foregroundStyle(Design.secondary).lineSpacing(4)
                }.padding(.top, 12)
            }.padding(28).frame(maxWidth: 500)
        }.frame(maxWidth: .infinity).background(Design.background).scrollDismissesKeyboard(.interactively)
    }
}
