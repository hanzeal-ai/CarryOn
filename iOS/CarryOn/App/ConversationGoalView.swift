import SwiftUI
import CarryOnCore

struct ConversationGoalView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ConversationActionTarget
    @State private var objective = ""
    @State private var budget = ""
    @State private var submitting = false
    @State private var refreshing = false
    @State private var failure: String?
    private var controls: JSONValue { model.snapshot(for: target)["controls"] }
    private var goal: JSONValue { controls["goal"] }
    private var valid: Bool {
        !objective.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (budget.isEmpty || (Int(budget).map { $0 > 0 && $0 <= 9_007_199_254_740_991 } ?? false))
    }
    private func allowed(_ action: String) -> Bool {
        !submitting && !refreshing && controls["goalUnknown"].bool != true && controls["supportsGoal"].bool == true && model.canPerform(target, action: action)
    }
    var body: some View {
        NavigationStack {
            Form {
                if controls["goalUnknown"].bool == true {
                    Section {
                        Text("目标状态尚未确认，请先核对，避免重复启动。")
                        Button(refreshing ? "正在核对…" : "核对目标状态") { Task { await refresh() } }.disabled(refreshing)
                    }
                }
                if goal != .null {
                    Section {
                        LabeledContent("状态", value: goalStatus(goal["status"].text))
                        LabeledContent("已用 Token", value: String(goal["tokensUsed"].int ?? 0))
                        if let limit = goal["tokenBudget"].int { LabeledContent("Token 预算", value: String(limit)) }
                        LabeledContent("已用时间", value: "\(goal["timeUsedSeconds"].int ?? 0) 秒")
                    }
                }
                Section("目标") {
                    TextField("希望完成什么", text: $objective, axis: .vertical).lineLimit(3...10)
                    TextField(goal == .null ? "Token 预算（可选）" : "新 Token 预算（留空保留）", text: $budget).keyboardType(.numberPad)
                    Text("启动后会持续执行，直到目标完成、暂停或达到限制。").font(.caption).foregroundStyle(Design.secondary)
                    Button(goal == .null ? "启动目标" : "保存目标") {
                        var fields: [String: JSONValue] = ["objective": .string(objective)]
                        if let amount = Int(budget) { fields["tokenBudget"] = .number(Double(amount)) }
                        if goal == .null { fields["status"] = .string("active") }
                        Task { await submit("goal-set", fields: fields) }
                    }.disabled(!allowed("goal-set") || !valid)
                }
                if goal != .null {
                    Section {
                        if goal["status"].text == "active" {
                            Button("暂停目标") { Task { await submit("goal-pause") } }.disabled(!allowed("goal-pause"))
                        } else if goal["status"].text != "complete" {
                            Button("继续目标") { Task { await submit("goal-set", fields: ["status": .string("active")]) } }.disabled(!allowed("goal-set"))
                        }
                        if goal["status"].text != "complete" {
                            Button("标记为完成") { Task { await submit("goal-set", fields: ["status": .string("complete")]) } }.disabled(!allowed("goal-set"))
                        }
                        Button("移除目标", role: .destructive) { Task { await submit("goal-clear") } }.disabled(!allowed("goal-clear"))
                        Text("暂停或移除目标会停止后续自动执行；当前轮次可在对话中单独停止。").font(.caption).foregroundStyle(Design.secondary)
                    }
                }
                if let failure { Text(failure).foregroundStyle(.red).accessibilityIdentifier("goal-error") }
            }.disabled(submitting).navigationTitle("会话目标").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() }.disabled(submitting) } }
                .onAppear { objective = goal["objective"].text }
                .onChange(of: goal) { old, new in
                    if objective == old["objective"].text { objective = new["objective"].text }
                }
        }.interactiveDismissDisabled(submitting)
    }
    private func refresh() async {
        guard !refreshing, target.scope == model.scope, target.threadID == model.selectedThread?.id else { return }
        refreshing = true; failure = nil; defer { refreshing = false }
        do {
            _ = try await model.deviceRequest(target.path("goal"))
            guard target.scope == model.scope, target.threadID == model.selectedThread?.id else { return }
            model.retryHistory()
        } catch { if target.scope == model.scope, target.threadID == model.selectedThread?.id { failure = error.localizedDescription } }
    }
    private func submit(_ action: String, fields: [String: JSONValue] = [:]) async {
        guard allowed(action) else { return }
        submitting = true; failure = nil; defer { submitting = false }
        if await model.perform(action, target: target, fields: fields) { budget = ""; model.retryHistory() }
        else if target.scope == model.scope, target.threadID == model.selectedThread?.id { failure = model.error ?? "尚未确认目标变更，请核对请求记录" }
    }
    private func goalStatus(_ status: String) -> String {
        switch status {
        case "active": "进行中"
        case "paused": "已暂停"
        case "blocked": "受阻"
        case "usageLimited": "已达用量限制"
        case "budgetLimited": "已达预算"
        case "complete": "已完成"
        default: status
        }
    }
}
