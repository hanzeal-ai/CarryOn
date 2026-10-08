import SwiftUI
import CarryOnCore

struct CreationConfigurationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Binding var selection: JSONValue
    let scope: String
    @State private var mode = "inherit"
    @State private var approval = "inherit"
    @State private var initialized = false
    private var fields: [JSONValue] { model.status["supportedCreationSettings"].array }
    private var editable: Bool { scope == model.scope && model.canWrite(.create) && model.canWrite(.edit) }
    private var modelSelected: Bool { !selection["model"].text.isEmpty }
    var body: some View {
        NavigationStack {
            Form {
                if fields.contains(.string("collaborationMode")) {
                    Picker("工作模式", selection: $mode) {
                        Text("项目默认").tag("inherit")
                        Text("执行").tag("default")
                        Text("计划").tag("plan")
                    }.disabled(!editable)
                    if mode != "inherit" && !modelSelected { Text("指定工作模式前，请先选择模型。").font(.caption).foregroundStyle(Design.secondary) }
                }
                if fields.contains(.string("approvalPolicy")) {
                    Picker("执行审批", selection: $approval) {
                        Text("项目默认").tag("inherit")
                        Text("按需请求").tag("on-request")
                        Text("不可信命令请求").tag("untrusted")
                        Text("不请求").tag("never")
                        if approval == "custom" { Text("自定义策略").tag("custom") }
                    }.disabled(!editable)
                }
            }.navigationTitle("新会话配置").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("完成") {
                            guard editable, (mode == "inherit" || modelSelected) else { return }
                            var values = selection.object ?? [:]
                            if fields.contains(.string("approvalPolicy")) {
                                if approval == "inherit" { values.removeValue(forKey: "approvalPolicy") }
                                else if approval != "custom" { values["approvalPolicy"] = .string(approval) }
                            }
                            if fields.contains(.string("collaborationMode")) {
                                if mode == "inherit" { values.removeValue(forKey: "collaborationMode") }
                                else {
                                    var settings = selection["collaborationMode"]["settings"].object ?? [:]
                                    settings["model"] = selection["model"]
                                    settings["reasoning_effort"] = selection["effort"]
                                    settings["developer_instructions"] = settings["developer_instructions"] ?? .null
                                    values["collaborationMode"] = .object(["mode": .string(mode), "settings": .object(settings)])
                                }
                            }
                            selection = values.isEmpty ? .null : .object(values)
                            dismiss()
                        }.disabled(!editable || (mode != "inherit" && !modelSelected))
                    }
                }
                .onAppear {
                    guard !initialized else { return }; initialized = true
                    mode = selection["collaborationMode"]["mode"].string ?? "inherit"
                    approval = selection["approvalPolicy"] == .null ? "inherit" : selection["approvalPolicy"].string ?? "custom"
                }
        }.presentationDetents([.medium])
    }
}
