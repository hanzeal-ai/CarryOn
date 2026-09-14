import SwiftUI
import CarryOnCore

struct CloudSettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""
    @State private var failure: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("自定义云端") {
                    TextField("https://…", text: $address)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        .accessibilityLabel("自定义云端地址")
                    if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                }
            }
            .scrollContentBackground(.hidden).background(Design.background)
            .navigationTitle("高级设置").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        do {
                            let validated = try ConsoleAddress(address).base.absoluteString
                            guard !model.authenticated, !model.busy else { return }
                            if (try? ConsoleAddress(model.addressText).base.absoluteString) != validated {
                                model.credential = ""
                                model.username = ""
                            }
                            model.addressText = validated
                            UserDefaults.standard.set(validated, forKey: "carryon.server")
                            dismiss()
                        } catch { failure = error.localizedDescription }
                    }.disabled(model.busy || model.authenticated || address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }.onAppear { address = model.addressText }
    }
}
