import SwiftUI
import CarryOnCore

struct ActivityRow: View {
    @Environment(AppModel.self) private var model
    let record: Record
    let scope: String
    var dimmed = false
    var beforeOpen: (() -> Void)?
    @State private var showingDetails = false
    @State private var pendingOpen: JSONValue?
    @State private var readThrough = 0
    @State private var loading = false
    @State private var failure: String?
    private var target: ConversationActionTarget { .init(scope: scope, threadID: record.id, isActivity: true) }
    private var snapshot: JSONValue { model.snapshot(for: target) }
    private var detail: ActivityDetail { ActivityDetail(history: snapshot) }
    private var kind: ActivityDetail.Kind {
        if snapshot != .null { return detail.kind }
        switch record.value["activityKind"].text {
        case "approval": return .approval
        case "question": return .question
        case "failed": return .failed
        case "completed": return .completed
        case "other": return .other
        default: break
        }
        if record.value["failed"].bool == true { return .failed }
        if record.value["status"]["state"].text == "waiting" { return .approval }
        return .other
    }
    private var label: String {
        if snapshot != .null { return detail.label }
        switch kind {
        case .completed: return "任务完成"
        case .failed: return "执行失败"
        case .approval: return "任务需要审核"
        case .question: return "需要回答问题"
        case .other: return record.value["status"]["label"].string ?? "会话更新"
        }
    }
    private var unread: Bool {
        record.value["unread"].bool == true && (readThrough == 0 || (record.value["readSequence"].int ?? 0) > readThrough)
    }
    private var timestamp: String? {
        if kind == .completed {
            if let time = detail.completedAt { return "完成于 " + date(time) }
            if case .number(let time) = record.value["completedAt"] { return "完成于 " + date(time) }
        }
        if case .number(let time) = record.value["updated_at"] { return "更新于 " + date(time) }
        return nil
    }
    var body: some View {
        Button {
            if kind == .completed || kind == .failed { Task { await openResult() } }
            else { showingDetails = true }
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Circle().fill(unread ? Design.blue : .clear).frame(width: 8, height: 8).padding(.top, 6)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 7) {
                    Text(record.title).font(.system(size: 15, weight: .semibold)).foregroundStyle(Design.ink).lineLimit(2)
                    Text(record.value["projectName"].string ?? "最近").font(.caption).foregroundStyle(Design.secondary)
                    Text(label).font(.caption).foregroundStyle(Design.secondary)
                    if let timestamp { Text(timestamp).font(.caption2).foregroundStyle(Design.secondary) }
                    if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
                }.frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: "chevron.right").font(.caption2).foregroundStyle(Design.secondary)
            }.contentShape(Rectangle())
        }.buttonStyle(.plain).disabled(loading).opacity(dimmed ? 0.6 : 1)
            .accessibilityValue(unread ? "未读" : "已读")
            .padding(.horizontal, 15).padding(.vertical, 17).frame(maxWidth: .infinity, alignment: .leading)
            .sheet(isPresented: $showingDetails, onDismiss: {
                if target.scope == model.scope { model.activitySnapshots.removeValue(forKey: record.id) }
                if let value = pendingOpen, target.scope == model.scope {
                    pendingOpen = nil
                    beforeOpen?()
                    model.openActivity(record, snapshot: value, anchor: ActivityDetail(history: value).anchorID)
                }
            }) {
                NavigationStack {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 18) {
                            Text(record.title).font(.headline)
                            Text(label).font(.subheadline).foregroundStyle(Design.secondary)
                            if loading && snapshot == .null { ProgressView("正在读取详情…") }
                            if let failure {
                                Text(failure).font(.caption).foregroundStyle(.red)
                                Button("重试") { Task { await load() } }.disabled(loading)
                            }
                            if snapshot != .null {
                                content
                                Button("进入会话") { pendingOpen = snapshot; showingDetails = false }
                                    .buttonStyle(.bordered)
                            }
                        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
                    }.background(Design.background)
                        .navigationTitle("动态详情").navigationBarTitleDisplayMode(.inline)
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { showingDetails = false } } }
                }
                .environment(\.conversationContentContext, ConversationContentContext(isReadOnly: snapshot["access"]["canInteract"].bool == false))
                .presentationDetents([.large]).presentationDragIndicator(.visible)
                .task {
                    guard target.scope == model.scope else { return }
                    model.activitySnapshots[record.id] = .null
                    await load()
                }
                .onChange(of: model.workspaceRevision) { _, _ in Task { await load() } }
            }
            .onChange(of: model.scope) { _, _ in showingDetails = false; pendingOpen = nil }
            .onDisappear { if target.scope == model.scope { model.activitySnapshots.removeValue(forKey: record.id) } }
    }
    @ViewBuilder private var content: some View {
        if !detail.requests.isEmpty || !detail.questions.isEmpty {
            ForEach(detail.requests, id: \.requestKey) { request in
                NativeRequestView(request: request, target: target).id(request.requestKey)
            }
            ForEach(detail.questions, id: \.stableID) { question in
                AsyncQuestionView(question: question, threadID: record.id, activityTarget: target)
            }
        } else if let failure = detail.failure {
            Text(failure).font(.subheadline).foregroundStyle(.red).textSelection(.enabled)
        } else if detail.kind == .completed, detail.result != .null {
            TimelineEntry(item: detail.result.setting("asyncQuestions", .array([])), threadID: record.id)
        } else if !snapshot["pendingRequests"].array.isEmpty {
            Text("此请求类型需要在 Codex App 处理").font(.caption).foregroundStyle(Design.secondary)
        } else {
            Text(detail.kind == .completed ? "此轮没有提供最终结果" : "当前没有待处理事项或最终结果")
                .font(.caption).foregroundStyle(Design.secondary)
        }
    }
    private func openResult() async {
        guard !loading, scope == model.scope else { return }
        loading = true; failure = nil
        model.activitySnapshots[record.id] = .null
        defer {
            loading = false
            if !showingDetails && scope == model.scope { model.activitySnapshots.removeValue(forKey: record.id) }
        }
        do {
            try await model.loadActivity(target)
            guard scope == model.scope else { return }
            let value = snapshot, latest = ActivityDetail(history: value)
            if latest.kind == .approval || latest.kind == .question { showingDetails = true; return }
            beforeOpen?()
            model.openActivity(record, snapshot: value, anchor: latest.anchorID)
        } catch { if scope == model.scope { failure = error.localizedDescription } }
    }
    private func date(_ value: Double) -> String { Date(timeIntervalSince1970: value).formatted(date: .abbreviated, time: .shortened) }
    private func load() async {
        guard !loading, showingDetails, target.scope == model.scope else { return }
        loading = true; defer { loading = false }
        do {
            try await model.loadActivity(target)
            failure = nil
            let sequence = record.value["readSequence"].int ?? 0
            if unread, sequence > readThrough, showingDetails, model.foreground {
                do {
                    let receipt = try await model.deviceRequest("/api/notifications/read", body: .object([
                        "threadId": .string(record.id), "sequence": .number(Double(sequence))
                    ]))
                    guard !Task.isCancelled, target.scope == model.scope else { return }
                    readThrough = max(readThrough, receipt["readThrough"].int ?? 0)
                    try await model.refreshActivityCounts()
                } catch { model.report(error, operation: "同步已读状态", blocking: false) }
            }
        } catch is CancellationError { return }
        catch {
            guard target.scope == model.scope, showingDetails, model.activitySnapshots[record.id] != nil else { return }
            model.activitySnapshots[record.id] = .null
            failure = error.localizedDescription
        }
    }
}
