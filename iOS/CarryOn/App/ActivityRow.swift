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
    @State private var loadVersion = UUID()
    @State private var failure: String?
    private var target: ConversationActionTarget { .init(scope: scope, threadID: record.id, isActivity: true) }
    private var snapshot: JSONValue { model.snapshot(for: target) }
    private var preview: JSONValue { record.value["activityPreview"] }
    private var previewText: String? {
        guard let text = preview["text"].string, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return text
    }
    private var showInitialLoading: Bool { loading && snapshot == .null && previewText == nil }
    private var detail: ActivityDetail { ActivityDetail(history: snapshot) }
    private var kind: ActivityDetail.Kind {
        if snapshot != .null { return detail.kind }
        if let kind = ActivityDetail.Kind(rawValue: preview["kind"].string ?? record.value["activityKind"].text) { return kind }
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
        Button { openDetails() } label: {
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
        }.buttonStyle(.plain).opacity(dimmed ? 0.6 : 1)
            .accessibilityValue(unread ? "未读" : "已读")
            .padding(.horizontal, 15).padding(.vertical, 17).frame(maxWidth: .infinity, alignment: .leading)
            .sheet(isPresented: $showingDetails, onDismiss: {
                closeDetails()
                if let value = pendingOpen, target.scope == model.scope {
                    pendingOpen = nil
                    beforeOpen?()
                    if value == .null { model.open(record) }
                    else { model.openActivity(record, snapshot: value, anchor: ActivityDetail(history: value).anchorID) }
                }
            }) {
                NavigationStack {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 18) {
                            Text(record.title).font(.headline)
                            Text(label).font(.subheadline).foregroundStyle(Design.secondary)
                            if snapshot == .null, let text = previewText {
                                MessageMarkdown(text: text, resolveCreatedThreads: false)
                                if preview["truncated"].bool == true {
                                    Text("进入会话查看完整内容").font(.caption).foregroundStyle(Design.secondary)
                                }
                            }
                            if showInitialLoading { ProgressView("正在加载详情…") }
                            if let failure {
                                Text(failure).font(.caption).foregroundStyle(.red)
                                Button("重试") { Task { await load() } }.disabled(loading)
                            }
                            if snapshot != .null { content }
                            Button("进入会话") { pendingOpen = snapshot; showingDetails = false }
                                .buttonStyle(.bordered)
                        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
                    }.background(Design.background)
                        .navigationTitle("动态详情").navigationBarTitleDisplayMode(.inline)
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { showingDetails = false } } }
                }
                .environment(\.conversationContentContext, ConversationContentContext(isReadOnly: snapshot["access"]["canInteract"].bool == false))
                .presentationDetents([.large]).presentationDragIndicator(.visible)
                .task {
                    guard target.scope == model.scope else { return }
                    await load()
                }
                .onChange(of: model.workspaceRevision) { _, _ in Task { await load() } }
            }
            .onChange(of: model.scope) { _, _ in showingDetails = false; pendingOpen = nil }
            .onDisappear { closeDetails() }
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
    private func date(_ value: Double) -> String { Date(timeIntervalSince1970: value).formatted(date: .abbreviated, time: .shortened) }
    private func openDetails() {
        guard target.scope == model.scope else { return }
        loadVersion = UUID(); loading = false; failure = nil
        model.beginActivity(target, preview: preview)
        showingDetails = true
    }
    private func closeDetails() {
        loadVersion = UUID(); loading = false
        model.endActivity(target)
    }
    private func load() async {
        guard !loading, showingDetails, target.scope == model.scope else { return }
        let version = UUID(); loadVersion = version
        loading = true; defer { if loadVersion == version { loading = false } }
        let sequence = record.value["readSequence"].int ?? 0
        do {
            try await model.loadActivity(target)
            guard loadVersion == version, showingDetails, target.scope == model.scope else { return }
            failure = nil
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
            guard loadVersion == version, target.scope == model.scope, showingDetails, model.activitySnapshots[record.id] != nil else { return }
            failure = error.localizedDescription
        }
    }
}
