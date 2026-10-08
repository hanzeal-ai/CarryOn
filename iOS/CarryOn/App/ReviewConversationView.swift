import SwiftUI
import CarryOnCore

struct ReviewConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ConversationActionTarget
    var initialInstructions = ""
    var completed: () -> Void
    @State private var initialized = false
    @State private var kind = "uncommittedChanges"
    @State private var branch = ""
    @State private var commit = ""
    @State private var instructions = ""
    @State private var sending = false
    @State private var failure: String?
    private var snapshot: JSONValue { model.snapshot(for: target) }
    private var ready: Bool {
        model.canPerform(target, action: "review") && snapshot["status"]["state"].text == "idle"
            && snapshot["controls"]["supportedOperations"].array.contains(.string("review"))
            && snapshot["queue"]["messages"].array.isEmpty && snapshot["controls"]["requests"].array.isEmpty
    }
    private var valid: Bool {
        switch kind {
        case "baseBranch": !branch.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case "commit": !commit.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case "custom": !instructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        default: true
        }
    }
    var body: some View {
        NavigationStack {
            Form {
                Picker("审查范围", selection: $kind) {
                    Text("未提交的改动").tag("uncommittedChanges")
                    Text("对比分支").tag("baseBranch")
                    Text("指定提交").tag("commit")
                    Text("自定义审查").tag("custom")
                }
                switch kind {
                case "baseBranch": TextField("分支名称", text: $branch).textInputAutocapitalization(.never).autocorrectionDisabled()
                case "commit": TextField("提交 SHA", text: $commit).textInputAutocapitalization(.never).autocorrectionDisabled()
                case "custom": TextField("审查要求", text: $instructions, axis: .vertical).lineLimit(3...8)
                default: EmptyView()
                }
                Text("审查将在当前会话运行，结果显示在对话中。").font(.caption).foregroundStyle(Design.secondary)
                if !ready { Text("会话空闲且没有排队任务或待处理请求时可开始审查。").font(.caption).foregroundStyle(Design.secondary) }
                if let failure { Text(failure).foregroundStyle(.red).accessibilityIdentifier("review-error") }
            }.disabled(sending).navigationTitle("审查代码").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(sending) }
                    ToolbarItem(placement: .confirmationAction) {
                        Button(sending ? "正在启动…" : "开始审查") { Task { await start() } }.disabled(sending || !ready || !valid)
                    }
                }
        }.interactiveDismissDisabled(sending)
            .onAppear { if !initialized { initialized = true; if !initialInstructions.isEmpty { kind = "custom"; instructions = initialInstructions } } }
    }
    private func start() async {
        guard ready, valid, !sending else { return }
        sending = true; failure = nil; defer { sending = false }
        var review: JSONValue = .object(["type": .string(kind)])
        if kind == "baseBranch" { review = review.setting("branch", .string(branch.trimmingCharacters(in: .whitespacesAndNewlines))) }
        if kind == "commit" { review = review.setting("sha", .string(commit.trimmingCharacters(in: .whitespacesAndNewlines))) }
        if kind == "custom" { review = review.setting("instructions", .string(instructions)) }
        if await model.perform("review", target: target, fields: ["target": review]) { dismiss(); completed() }
        else if target.scope == model.scope, target.threadID == model.selectedThread?.id { failure = model.error ?? "尚未确认审查启动，请核对请求记录" }
    }
}
