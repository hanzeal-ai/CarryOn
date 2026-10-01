import SwiftUI
import CarryOnCore

struct CreationModelPicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Binding var selection: JSONValue
    let scope: String
    @State private var choices: [JSONValue] = []
    @State private var selected = ""
    @State private var effort = ""
    @State private var loading = true
    @State private var failure: String?
    private var efforts: [String] { choices.first { $0["id"].text == selected }?["efforts"].array.compactMap(\.string) ?? [] }
    private func normalizeEffort() {
        if !efforts.contains(effort) {
            let preferred = choices.first { $0["id"].text == selected }?["defaultEffort"].string
            effort = preferred.flatMap { efforts.contains($0) ? $0 : nil } ?? efforts.first ?? ""
        }
    }
    var body: some View {
        NavigationStack {
            Form {
                if loading { ProgressView("正在读取模型…") }
                Picker("模型", selection: $selected) {
                    Text("默认模型").tag("")
                    ForEach(choices, id: \.stableID) { Text($0["name"].text).tag($0["id"].text) }
                }.disabled(loading || scope != model.scope)
                if !selected.isEmpty {
                    Picker("思考强度", selection: $effort) {
                        ForEach(efforts, id: \.self) { Text($0).tag($0) }
                    }.disabled(loading || scope != model.scope)
                }
                if let failure { Text(failure).foregroundStyle(.red) }
            }.navigationTitle("模型与思考强度").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("完成") {
                            guard scope == model.scope else { return }
                            selection = selected.isEmpty ? .null : .object(["model": .string(selected), "effort": .string(effort)])
                            dismiss()
                        }.disabled(loading || scope != model.scope || (!selected.isEmpty && !efforts.contains(effort)))
                    }
                }
                .task {
                    loading = true; failure = nil
                    do {
                        let result = try await model.cachedDeviceRequest("/api/models", maxAge: 0)
                        guard !Task.isCancelled, scope == model.scope else { return }
                        choices = result["models"].array
                        let savedModel = selection["model"].text
                        if savedModel.isEmpty || choices.contains(where: { $0["id"].text == savedModel }) {
                            selected = savedModel
                            effort = selection["effort"].text
                            normalizeEffort()
                        } else {
                            selected = ""; effort = ""
                            failure = "此前选择的模型已不可用，请重新选择"
                        }
                    } catch { if scope == model.scope { failure = error.localizedDescription } }
                    loading = false
                }
                .onChange(of: selected) { _, _ in
                    guard !loading else { return }; normalizeEffort()
                }
        }.presentationDetents([.medium])
    }
}
