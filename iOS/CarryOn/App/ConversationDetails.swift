import SwiftUI
import CarryOnCore

func conversationLabel(_ key: String) -> String {
    ["latestModel": "当前模型", "latestReasoningEffort": "思考强度", "latestTokenUsageInfo": "用量",
     "gitInfo": "Git 信息", "branch": "分支", "commitHash": "提交", "sha": "提交", "originUrl": "仓库地址",
     "tokenUsage": "Token 用量", "total": "累计用量", "last": "本轮用量", "totalTokens": "总 Token",
     "inputTokens": "输入 Token", "outputTokens": "输出 Token", "cachedInputTokens": "缓存输入 Token",
     "reasoningOutputTokens": "推理输出 Token", "modelContextWindow": "上下文容量", "rateLimits": "用量限制",
     "id": "编号", "title": "标题", "type": "类型"][key] ?? key
}

func conversationValue(_ value: JSONValue) -> String {
    switch value {
    case .null: return "未设置"
    case .string(let text): return text.isEmpty ? "空" : text
    case .bool(let flag): return flag ? "开启" : "关闭"
    case .number(let number): return number.formatted()
    case .array(let values): return "\(values.count) 项"
    case .object: return value["type"].string.map(conversationLabel) ?? value["id"].string ?? "详细配置"
    }
}

struct ConversationValueRows: View {
    let value: JSONValue
    var body: some View {
        if let object = value.object {
            ForEach(object.keys.sorted(), id: \.self) { key in
                row(title: conversationLabel(key), value: object[key] ?? .null)
            }
        } else if case .array(let values) = value {
            ForEach(Array(values.enumerated()), id: \.offset) { index, item in row(title: "第 \(index + 1) 项", value: item) }
        } else { Text(conversationValue(value)).textSelection(.enabled) }
    }
    private func row(title: String, value: JSONValue) -> AnyView {
        if value.object != nil || { if case .array = value { return true }; return false }() {
            return AnyView(DisclosureGroup(title) { ConversationValueRows(value: value) })
        }
        return AnyView(HStack(alignment: .firstTextBaseline, spacing: 16) {
            Text(title).foregroundStyle(Design.secondary)
                .fixedSize(horizontal: true, vertical: false)
            Spacer(minLength: 0)
            Text(conversationValue(value)).textSelection(.enabled)
                .multilineTextAlignment(.trailing)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }.padding(.vertical, 4))
    }
}

struct StructuredDetail: View {
    let title: String
    let value: JSONValue
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                if value == .null || value.object?.isEmpty == true { Text("暂无信息").foregroundStyle(Design.secondary) }
                else { ConversationValueRows(value: value) }
            }.navigationTitle(title).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }
}
