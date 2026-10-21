import SwiftUI
import CarryOnCore

struct CreationModelPicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Binding var selection: JSONValue
    let scope: String
    var quick = false
    var onClose: (() -> Void)? = nil
    var onAdvanced: (() -> Void)? = nil
    @State private var choices: [JSONValue] = []
    @State private var selected = ""
    @State private var effort = ""
    @State private var loading = true
    @State private var failure: String?
    private var editable: Bool { scope == model.scope && model.canWrite(.create) && (selection.object?.keys.contains(where: { !["model", "effort"].contains($0) }) != true || model.canWrite(.edit)) }
    private var efforts: [String] { choices.first { $0["id"].text == selected }?["efforts"].array.compactMap(\.string) ?? [] }
    private func normalizeEffort() {
        if !efforts.contains(effort) {
            let preferred = choices.first { $0["id"].text == selected }?["defaultEffort"].string
            effort = preferred.flatMap { efforts.contains($0) ? $0 : nil } ?? efforts.first ?? ""
        }
    }
    var body: some View {
        Group {
          if quick {
            VStack(spacing: 8) {
                if loading { ProgressView().frame(minHeight: 44) }
                ReasoningEffortControl(modelName: ModelPresentation.name(selected.isEmpty ? "默认模型" : selected, catalog: .object(["models": .array(choices)])),
                    effort: effort, efforts: efforts, disabled: loading || !editable,
                    advanced: { onAdvanced?() }, choose: { value in
                        guard editable, !loading, efforts.contains(value) else { return }
                        effort = value; saveSelection()
                    })
                if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
            }
          } else {
            advancedContent
          }
        }
                .task {
                    loading = true; failure = nil
                    selected = selection["model"].text; effort = selection["effort"].text
                    do {
                        let result = try await model.cachedDeviceRequest("/api/models", maxAge: 0)
                        guard !Task.isCancelled, scope == model.scope else { return }
                        choices = result["models"].array
                        if !selected.isEmpty && !choices.contains(where: { $0["id"].text == selected }) {
                            failure = "此前选择的模型已不可用，请重新选择"
                        } else if !selected.isEmpty && !efforts.contains(effort) {
                            failure = "此前选择的思考强度已不可用，请重新选择"
                        }
                    } catch { if scope == model.scope { failure = error.localizedDescription } }
                    loading = false
                }
                .onChange(of: selected) { _, _ in
                    guard !loading else { return }; normalizeEffort()
                }

    }
    private var advancedContent: some View {
        NavigationStack {
            Form {
                if loading { ProgressView("正在读取模型…") }
                Picker("模型", selection: $selected) {
                    Text("默认模型").tag("")
                    if !selected.isEmpty && !choices.contains(where: { $0["id"].text == selected }) { Text("当前不可用：" + selected).tag(selected).disabled(true) }
                    ForEach(choices, id: \.stableID) { Text($0["name"].text).tag($0["id"].text) }
                }.disabled(loading || !editable)
                if !selected.isEmpty {
                    Picker("思考强度", selection: $effort) {
                        if !effort.isEmpty && !efforts.contains(effort) { Text("当前不可用：" + effort).tag(effort).disabled(true) }
                        ForEach(efforts, id: \.self) { Text(ModelPresentation.effort($0)).tag($0) }
                    }.disabled(loading || !editable)
                }
                if let failure { Text(failure).foregroundStyle(.red) }
            }.navigationTitle("高级").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { closePanel() } }.carryOnFlatToolbar()
                    ToolbarItem(placement: .confirmationAction) {
                        Button("完成") {
                            saveSelection()
                        }.disabled(loading || !editable || (!selected.isEmpty && !efforts.contains(effort)) || (selection["collaborationMode"] != .null && selected.isEmpty))
                    }
                }
          }
          .presentationDetents([.medium])
          .presentationDragIndicator(.visible)
          .presentationBackground(Color(uiColor: .systemGroupedBackground))
    }
    private func closePanel() { if let onClose { onClose() } else { dismiss() } }
    private func saveSelection() {
        guard editable, !loading, selected.isEmpty || efforts.contains(effort), selection["collaborationMode"] == .null || !selected.isEmpty else { return }
        var values = selection.object ?? [:]
        if selected.isEmpty { values.removeValue(forKey: "model"); values.removeValue(forKey: "effort") }
        else { values["model"] = .string(selected); values["effort"] = .string(effort) }
        if values["collaborationMode"] != nil, values["collaborationMode"] != .null {
            var settings = selection["collaborationMode"]["settings"].object ?? [:]
            settings["model"] = .string(selected); settings["reasoning_effort"] = .string(effort)
            values["collaborationMode"] = selection["collaborationMode"].setting("settings", .object(settings))
        }
        selection = values.isEmpty ? .null : .object(values)
        closePanel()
    }
}
