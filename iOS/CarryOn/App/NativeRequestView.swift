import SwiftUI
import CarryOnCore

struct NativeRequestView: View {
    @Environment(AppModel.self) private var model
    let request: JSONValue
    @State private var answers: [String: String] = [:]
    @State private var decision: JSONValue?
    @State private var permissions = ""
    @State private var permissionScope = "turn"
    @State private var strictReview = true
    @State private var responseText = ""
    var action: String { request["action"].text }
    var title: String { ["command-approval": "命令审批", "file-approval": "文件审批", "permissions-approval": "权限申请", "user-input": "回答问题", "mcp-response": "工具交互"][action] ?? "待处理请求" }
    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            Text(title).font(.system(size: 14, weight: .semibold))
            DisclosureGroup("查看请求内容") { Text(request["params"].formatted).font(.system(size: 11, design: .monospaced)).textSelection(.enabled) }.font(.caption)
            if ["command-approval", "file-approval"].contains(action) {
                ForEach(Array(request["decisions"].array.enumerated()), id: \.offset) { _, option in
                    Button(decisionLabel(option)) { decision = .object(["decision": option]) }.buttonStyle(.bordered).frame(minHeight: 44)
                }
            } else if action == "user-input" {
                ForEach(request["params"]["questions"].array, id: \.stableID) { question in
                    let id = question["id"].text
                    VStack(alignment: .leading, spacing: 8) {
                        Text(question["question"].string ?? question["header"].text).font(.subheadline)
                        ForEach(question["options"].array, id: \.formatted) { option in
                            Button { answers[id] = option["label"].text } label: {
                                VStack(alignment: .leading, spacing: 4) { Text(option["label"].text); if !option["description"].text.isEmpty { Text(option["description"].text).font(.caption).foregroundStyle(Design.secondary) } }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(answers[id] == option["label"].text ? Design.blue.opacity(0.08) : .white, in: RoundedRectangle(cornerRadius: 10))
                            }
                        }
                        if question["isSecret"].bool == true {
                            SecureField("输入回答", text: answer(id)).textContentType(.password).padding(12).background(.white, in: RoundedRectangle(cornerRadius: 12))
                        } else {
                            TextField("输入回答", text: answer(id), axis: .vertical).lineLimit(1...5).padding(12).background(.white, in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                }
                Button("提交回答") {
                    let questions = request["params"]["questions"].array
                    guard !questions.isEmpty, questions.allSatisfy({ !(answers[$0["id"].text] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else { model.error = "请回答全部问题"; return }
                    let values = answers.mapValues { JSONValue.array([.string($0)]) }
                    Task { await respond(["answers": .object(values)]) }
                }.buttonStyle(.borderedProminent).frame(minHeight: 44)
            } else if action == "permissions-approval" {
                Picker("授权有效期", selection: $permissionScope) { Text("仅本轮").tag("turn"); Text("整个会话").tag("session") }.pickerStyle(.segmented)
                TextField("授予权限 JSON", text: $permissions, axis: .vertical).font(.system(.caption, design: .monospaced)).lineLimit(3...12).padding(12).background(.white, in: RoundedRectangle(cornerRadius: 10))
                Toggle("继续逐条审查本轮命令", isOn: $strictReview).font(.caption)
                Button("授予所选权限") {
                    do { let value = try JSONDecoder().decode(JSONValue.self, from: Data(permissions.utf8)); guard value.object != nil else { throw APIError("权限必须是 JSON 对象") }; decision = .object(["response": .object(["permissions": value, "scope": .string(permissionScope), "strictAutoReview": .bool(strictReview)])]) } catch { model.report(error) }
                }.buttonStyle(.borderedProminent)
                Button("拒绝", role: .destructive) { Task { await respond(["decision": .string("decline")]) } }.frame(minHeight: 44)
            } else if action == "mcp-response" {
                TextField("回应内容（JSON 对象，可留空）", text: $responseText, axis: .vertical).lineLimit(2...8).font(.caption)
                Button("允许并提交") {
                    do { let content: JSONValue = responseText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? .null : try JSONDecoder().decode(JSONValue.self, from: Data(responseText.utf8)); guard content == .null || content.object != nil else { throw APIError("回应必须是 JSON 对象") }; decision = .object(["response": .object(["action": .string("accept"), "content": content])]) } catch { model.report(error) }
                }.buttonStyle(.borderedProminent)
                Button("拒绝", role: .destructive) { Task { await respond(["response": .object(["action": .string("decline")])]) } }.frame(minHeight: 44)
            } else { Text("请在 Codex App 处理此类型请求。").font(.caption) }
        }.padding(17).frame(maxWidth: .infinity, alignment: .leading).background(Design.background, in: RoundedRectangle(cornerRadius: 18))
            .disabled(!model.canWrite)
            .onAppear { permissions = request["params"]["permissions"].formatted }
            .alert("确认已查看请求与授权范围？", isPresented: Binding(get: { decision != nil }, set: { if !$0 { decision = nil } })) {
                Button("取消", role: .cancel) { decision = nil }
                Button("确认提交") { if let value = decision { Task { await respond(value.object ?? [:]) } }; decision = nil }
            } message: { Text(decision?.formatted ?? "") }
    }
    private func answer(_ id: String) -> Binding<String> { Binding(get: { answers[id] ?? "" }, set: { answers[id] = $0 }) }
    private func respond(_ fields: [String: JSONValue]) async {
        // Bind approval to the exact server request and its fingerprint, never just a label.
        guard model.history["controls"]["requests"].array.contains(where: { $0.requestKey == request.requestKey }) else { model.error = "请求已改变，请刷新后重新核对"; return }
        var body = fields; body["nativeRequestId"] = request["id"]; body["requestFingerprint"] = request["fingerprint"]
        _ = await model.operation(action, fields: body)
    }
    private func decisionLabel(_ value: JSONValue) -> String {
        if let text = value.string { return ["accept": "仅本次允许", "acceptForSession": "在此会话中允许", "decline": "拒绝", "cancel": "取消并中断"][text] ?? text }
        if value["acceptWithExecpolicyAmendment"] != .null { return "允许并保存命令规则" }
        if value["applyNetworkPolicyAmendment"] != .null { return "应用网络规则（查看详情）" }
        return "应用审批选项（查看详情）"
    }
}
