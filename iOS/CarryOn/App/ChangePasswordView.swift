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
            Form {
                SecureField("当前密码", text: $current).textContentType(.password)
                SecureField("新密码（至少 12 位）", text: $password).textContentType(.newPassword)
                SecureField("再次输入新密码", text: $confirmation).textContentType(.newPassword)
                if let failure { Text(failure).foregroundStyle(.red) }
                Button("保存并重新登录") { Task { await save() } }
                    .disabled(busy || current.isEmpty || password.count < 12 || password != confirmation)
            }.navigationTitle("修改密码")
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(busy) } }
        }
    }
    private func save() async {
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
