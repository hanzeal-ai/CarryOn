import SwiftUI
import CarryOnCore

struct NativeRequestView: View {
    @Environment(AppModel.self) private var model
    let request: JSONValue
    let target: ConversationActionTarget
    @State private var answers: [String: String] = [:]
    @State private var submitted = false
    @State private var failure: String?
    @State private var pendingDecision: JSONValue?
    @State private var permissionScope = "turn"
    @State private var strictReview = true
    @State private var formValues: [String: String] = [:]
    private var schema: JSONValue { request["params"]["requestedSchema"] }
    var action: String { request["action"].text }
    var title: String { ["command-approval": "命令审批", "file-approval": "文件审批", "permissions-approval": "权限申请", "user-input": "回答问题", "mcp-response": "工具交互"][action] ?? "待处理请求" }
    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            Text(title).font(.system(size: 14, weight: .semibold))
            RequestSummary(params: request["params"], action: action)
            if submitted { Label("回应已提交，等待同步", systemImage: "checkmark.circle").font(.caption).foregroundStyle(Design.secondary) }
            if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
            if ["command-approval", "file-approval"].contains(action) {
                ForEach(Array(request["decisions"].array.enumerated()), id: \.offset) { _, option in
                    Button(decisionLabel(option)) {
                        if option.object != nil { pendingDecision = option }
                        else { Task { await respond(["decision": option]) } }
                    }.buttonStyle(.bordered).frame(minHeight: 44)
                }
            } else if action == "user-input" {
                ForEach(request["params"]["questions"].array, id: \.stableID) { question in
                    let id = question["id"].text
                    VStack(alignment: .leading, spacing: 8) {
                        Text(question["question"].string ?? question["header"].text).font(.subheadline)
                        ForEach(question["options"].array, id: \.formatted) { option in
                            Button { answers[id] = option["label"].text } label: {
                                VStack(alignment: .leading, spacing: 4) { Text(option["label"].text); if !option["description"].text.isEmpty { Text(option["description"].text).font(.caption).foregroundStyle(Design.secondary) } }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(answers[id] == option["label"].text ? Design.blue.opacity(0.08) : Design.surface, in: RoundedRectangle(cornerRadius: 10))
                            }
                        }
                        if question["isSecret"].bool == true {
                            SecureField("输入回答", text: answer(id)).textContentType(.password).padding(12).background(Design.surface, in: RoundedRectangle(cornerRadius: 12))
                        } else {
                            TextField("输入回答", text: answer(id), axis: .vertical).lineLimit(1...5).padding(12).background(Design.surface, in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                }
                Button("提交回答") {
                    let questions = request["params"]["questions"].array
                    guard !questions.isEmpty, questions.allSatisfy({ !(answers[$0["id"].text] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else { model.error = "请回答全部问题"; return }
                    let values = answers.mapValues { JSONValue.array([.string($0)]) }
                    Task { await respond(["answers": .object(values)]) }
                }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent).frame(minHeight: 44)
            } else if action == "permissions-approval" {
                Picker("授权有效期", selection: $permissionScope) { Text("仅本轮").tag("turn"); Text("整个会话").tag("session") }.pickerStyle(.segmented)
                Toggle("继续逐条审查本轮命令", isOn: $strictReview).font(.caption)
                Button("允许请求的权限") { Task {
                    await respond(["response": .object(["permissions": request["params"]["permissions"], "scope": .string(permissionScope), "strictAutoReview": .bool(strictReview)])])
                } }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent)
                Button("拒绝", role: .destructive) { Task { await respond(["decision": .string("decline")]) } }.frame(minHeight: 44)
            } else if action == "mcp-response" {
                if ElicitationForm.supports(schema) {
                    ForEach((schema["properties"].object ?? [:]).keys.sorted(), id: \.self) { key in
                        elicitationField(key, field: schema["properties"][key])
                    }
                    Button("提交") { Task {
                        do { await respond(["response": .object(["action": .string("accept"), "content": try ElicitationForm.response(schema, values: formValues)])]) }
                        catch { failure = error.localizedDescription }
                    } }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent)
                } else { Text("此请求包含暂不支持的表单，请在 Codex App 完成。").font(.caption).foregroundStyle(Design.secondary) }
                HStack {
                    Button("拒绝", role: .destructive) { Task { await respond(["response": .object(["action": .string("decline")])]) } }
                    Button("取消请求") { Task { await respond(["response": .object(["action": .string("cancel")])]) } }
                }.frame(minHeight: 44)
            } else { Text("请在 Codex App 处理此类型请求。").font(.caption) }
        }.padding(17).frame(maxWidth: .infinity, alignment: .leading).background(Design.background, in: RoundedRectangle(cornerRadius: 18))
            .disabled(!model.canPerform(target, action: action) || submitted)
            .sheet(isPresented: Binding(get: { pendingDecision != nil }, set: { if !$0 { pendingDecision = nil } })) {
                NavigationStack {
                    ScrollView { VStack(alignment: .leading, spacing: 16) {
                        Text("核对将应用的审批规则").font(.headline)
                        ConversationValueRows(value: pendingDecision ?? .null)
                        Button("确认应用此规则") { Task {
                            if let value = pendingDecision { await respond(["decision": value]) }
                            if submitted { pendingDecision = nil }
                        } }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent).disabled(!model.canPerform(target, action: action) || submitted)
                        if let failure { Text(failure).foregroundStyle(.red) }
                    }.padding(16) }
                    .navigationTitle("审批规则").navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { pendingDecision = nil } } }
                }
            }
    }
    @ViewBuilder private func elicitationField(_ key: String, field: JSONValue) -> some View {
        let label = field["title"].string ?? key
        let value = Binding(get: { formValues[key] ?? "" }, set: { formValues[key] = $0 })
        VStack(alignment: .leading, spacing: 6) {
            Text(label + (schema["required"].array.contains(.string(key)) ? " *" : "")).font(.subheadline)
            if !field["description"].text.isEmpty { Text(field["description"].text).font(.caption).foregroundStyle(Design.secondary) }
            if !field["enum"].array.isEmpty {
                Picker(label, selection: value) {
                    Text("请选择").tag("")
                    ForEach(field["enum"].array, id: \.formatted) { option in Text(conversationValue(option)).tag(option.formatted) }
                }.pickerStyle(.menu)
            } else if field["type"].text == "boolean" {
                Picker(label, selection: value) { Text("请选择").tag(""); Text("是").tag("true"); Text("否").tag("false") }.pickerStyle(.segmented)
            } else {
                TextField(label, text: value, axis: .vertical).lineLimit(1...5).textFieldStyle(.roundedBorder)
            }
        }
    }
    private func answer(_ id: String) -> Binding<String> { Binding(get: { answers[id] ?? "" }, set: { answers[id] = $0 }) }
    private func respond(_ fields: [String: JSONValue]) async {
        guard model.canPerform(target, action: action), model.snapshot(for: target)["controls"]["requests"].array.contains(where: { $0.requestKey == request.requestKey }) else {
            failure = "请求已改变或会话已切换，请重新核对"; return
        }
        var body = fields; body["nativeRequestId"] = request["id"]; body["requestFingerprint"] = request["fingerprint"]
        if await model.perform(action, target: target, fields: body) { submitted = true; failure = nil }
        else { failure = model.error }
    }
    private func decisionLabel(_ value: JSONValue) -> String {
        if let text = value.string { return ["accept": "仅本次允许", "acceptForSession": "在此会话中允许", "decline": "拒绝", "cancel": "取消并中断"][text] ?? text }
        if value["acceptWithExecpolicyAmendment"] != .null { return "允许并保存命令规则" }
        if value["applyNetworkPolicyAmendment"] != .null { return "应用网络规则（查看详情）" }
        return "应用审批选项（查看详情）"
    }
}

private struct RequestSummary: View {
    let params: JSONValue
    let action: String
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(["reason", "message"], id: \.self) { key in
                if !params[key].text.isEmpty { Text(params[key].text).fixedSize(horizontal: false, vertical: true) }
            }
            if params["command"] != .null {
                CodeBlockView(code: params["command"].string ?? params["command"].array.map(\.text).joined(separator: " "), language: "shell")
            }
            if !params["cwd"].text.isEmpty { Label(params["cwd"].text, systemImage: "folder").font(.caption).textSelection(.enabled) }
            if action == "permissions-approval" { ConversationValueRows(value: params["permissions"]) }
            if action == "file-approval" {
                ConversationValueRows(value: params["changes"] == .null ? params : params["changes"])
            }
            DisclosureGroup("请求详情") { ConversationValueRows(value: params) }.font(.caption)
        }
    }
}
