import SwiftUI

@MainActor struct CloudAccountView: View {
    @ObservedObject var model: SettingsModel
    @Environment(\.dismiss) private var dismiss
    @State private var url: String
    @State private var configured: Bool?
    @State private var setupToken = ""
    @State private var currentUsername = ""
    @State private var currentPassword = ""
    @State private var username = ""
    @State private var password = ""
    @State private var confirmation = ""
    @State private var busy = false
    @State private var message = ""
    @State private var succeeded = false

    init(model: SettingsModel, initialURL: String = "") {
        self.model = model; _url = State(initialValue: initialURL)
    }
    static func consoleURL(_ value: String) -> String {
        guard var components = URLComponents(string: value) else { return value }
        if components.scheme == "wss" { components.scheme = "https" }
        if components.path.hasSuffix("/device") { components.path.removeLast(7) }
        return components.string ?? value
    }
    private var valid: Bool {
        !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && username.count <= 100 &&
        (12...256).contains(password.count) && password == confirmation &&
        (configured == true ? !currentUsername.isEmpty && !currentPassword.isEmpty : !setupToken.isEmpty)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { SymbolTile(name: "person.badge.key", color: DesktopDesign.blue); Text("云端账号").font(.title2.weight(.semibold)) }
            TextField("云端 HTTPS 地址", text: $url).textFieldStyle(.roundedBorder)
                .onChange(of: url) { _ in configured = nil; clearSecrets(); message = ""; succeeded = false }
            if let configured, !succeeded {
                Text(configured ? "修改账号密码" : "首次设置账号密码").font(.headline)
                if configured {
                    TextField("当前账号", text: $currentUsername).textFieldStyle(.roundedBorder)
                    SecureField("当前密码", text: $currentPassword).textFieldStyle(.roundedBorder)
                } else {
                    SecureField("一次性初始化凭证", text: $setupToken).textFieldStyle(.roundedBorder)
                    Text("由服务器管理员生成，10 分钟内有效。").font(.caption).foregroundStyle(DesktopDesign.secondary)
                }
                TextField("新账号", text: $username).textFieldStyle(.roundedBorder)
                SecureField("新密码（12–256 位）", text: $password).textFieldStyle(.roundedBorder)
                SecureField("再次输入新密码", text: $confirmation).textFieldStyle(.roundedBorder)
                Text("保存后，已有登录将失效。").font(.caption).foregroundStyle(DesktopDesign.secondary)
            }
            if !message.isEmpty { Text(message).font(.caption).foregroundStyle(succeeded ? DesktopDesign.green : .red).textSelection(.enabled) }
            HStack {
                if busy { ProgressView().controlSize(.small) }
                Spacer()
                Button(succeeded ? "完成" : "取消") { clearSecrets(); dismiss() }.keyboardShortcut(.cancelAction)
                if !succeeded {
                    if configured == nil {
                        Button("继续") { Task { await inspect() } }.buttonStyle(AccentButton()).disabled(url.isEmpty)
                    } else {
                        Button("保存") { Task { await save() } }.buttonStyle(AccentButton()).disabled(!valid)
                    }
                }
            }
        }.padding(28).frame(width: 470).background(DesktopDesign.background).disabled(busy)
            .interactiveDismissDisabled(busy).onDisappear { clearSecrets() }
    }
    private func clearSecrets() { setupToken = ""; currentPassword = ""; password = ""; confirmation = "" }
    private func inspect() async {
        busy = true; defer { busy = false }
        let result = await model.call(["cloud", "account", "status", "--url", url.trimmingCharacters(in: .whitespacesAndNewlines)])
        if result.code == 0, let value = model.object(result.text)?["configured"] as? Bool {
            configured = value; message = ""
        } else { message = result.text }
    }
    private func save() async {
        busy = true; defer { busy = false }
        let result = await model.configureAccount(url: url.trimmingCharacters(in: .whitespacesAndNewlines),
            action: configured == true ? "change" : "setup",
            fields: ["setupToken": setupToken, "currentUsername": currentUsername, "currentPassword": currentPassword,
                     "username": username.trimmingCharacters(in: .whitespacesAndNewlines), "password": password])
        clearSecrets(); message = result.text; succeeded = result.code == 0
    }
}
