import SwiftUI
import CarryOnCore

struct ChangePasswordView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var current = ""
    @State private var password = ""
    @State private var confirmation = ""
    @State private var busy = false
    @State private var failure: String?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    VStack(spacing: 12) {
                        SecureField("当前密码", text: $current).textContentType(.password)
                        SecureField("新密码（至少 12 位）", text: $password).textContentType(.newPassword)
                        SecureField("再次输入新密码", text: $confirmation).textContentType(.newPassword)
                    }.textFieldStyle(PasswordFieldStyle()).disabled(busy)
                    if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                    Button { Task { await save() } } label: {
                        HStack {
                            Spacer()
                            if busy { ProgressView().tint(Design.onAccent) }
                            else { Text("保存并重新登录").fontWeight(.semibold) }
                            Spacer()
                        }.frame(minHeight: 50)
                    }.foregroundStyle(Design.onAccent)
                        .background(Design.ink, in: RoundedRectangle(cornerRadius: Design.controlCorner))
                        .disabled(!canSave).opacity(canSave || busy ? 1 : 0.4)
                }.padding(20)
            }.background(Design.background).scrollDismissesKeyboard(.interactively)
                .navigationBarTitleDisplayMode(.inline)
                .interactiveDismissDisabled(busy)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(busy) } }
        }
    }
    private var canSave: Bool { !busy && !current.isEmpty && password.count >= 12 && password == confirmation }
    private func save() async {
        guard canSave else { return }
        failure = nil
        let epoch = model.epoch
        busy = true; defer { busy = false }
        do {
            _ = try await model.console("password", body: .object(["currentPassword":.string(current), "password":.string(password)]))
            guard epoch == model.epoch else { return }
            current = ""; password = ""; confirmation = ""
            await model.logout(); dismiss()
        } catch { failure = error.localizedDescription }
    }
}

private struct PasswordFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration.padding(15).background(Design.surface, in: RoundedRectangle(cornerRadius: Design.controlCorner))
    }
}
