import SwiftUI
import CarryOnCore

/// Both menu selection and inline references enter the existing ConversationView.
struct SubagentsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let parentID: String
    let onOpen: () -> Void
    @State private var threads: [Record] = []
    @State private var loading = true
    @State private var failure: String?
    var body: some View {
        NavigationStack {
            List {
                if let failure { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { Task { await load() } }) }
                ForEach(threads) { thread in
                    Button { open(thread) } label: {
                        HStack { HStack(spacing: 4) { Image("CarryOnLogo").resizable().scaledToFit().frame(width: 16, height: 16); Text(thread.title) }; Spacer(); if thread.value["access"]["canInteract"].bool != true { Text("只读").font(.caption).foregroundStyle(Design.secondary) } }
                    }
                }
                if threads.isEmpty && failure == nil { BlankState(text: loading ? "正在加载子会话…" : "暂无子会话", loading: loading, symbol: "bubble.left.and.bubble.right") }
            }.navigationTitle("子会话").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .task(id: model.scope + parentID) { await load() }
                .refreshable { await load() }
        }
    }
    private func open(_ thread: Record) {
        guard model.selectedThread?.id == parentID else { return }
        dismiss(); onOpen(); model.enterSubconversation(thread, from: parentID)
    }
    private func load() async {
        let scope = model.scope
        loading = true; failure = nil
        defer { if model.scope == scope { loading = false } }
        do {
            let result = try await model.deviceRequest("/api/threads/\(ConsoleAddress.component(parentID))/subagents")
            guard !Task.isCancelled, model.scope == scope, model.selectedThread?.id == parentID else { return }
            guard case .array(let items) = result["threads"] else { throw APIError("子会话目录格式不正确") }
            threads = try items.map(Record.init)
            if threads.count == 1, let thread = threads.first { open(thread) }
        } catch { if !Task.isCancelled && model.scope == scope { failure = error.localizedDescription } }
    }
}

struct SubagentLinks: View {
    @Environment(AppModel.self) private var model
    let item: JSONValue
    let parentID: String
    @State private var opening = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
        ForEach(item["subagents"].array, id: \.stableID) { agent in
            Button {
                opening = true
                Task { await model.openSubagent(agent["id"].text, parentID: parentID); opening = false }
            } label: {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Image("CarryOnLogo").resizable().scaledToFit().frame(width: 14, height: 14)
                    Text(agent["title"].text)
                }
                    .font(.caption).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
            }.buttonStyle(.plain).foregroundStyle(Design.link).disabled(opening || model.selectedThread?.id != parentID)
        }
        }
    }
}

struct AgentActivityGroup: View {
    @Environment(AppModel.self) private var model
    let items: [JSONValue]
    let parentID: String
    var anchorID: String?
    @State private var opening = false
    private var rows: [(agent: JSONValue, state: ConversationState)] {
        var order: [String] = [], values: [String: (JSONValue, ConversationState)] = [:]
        for item in items {
            for agent in item["subagents"].array {
                let id = agent["id"].text
                if values[id] == nil { order.append(id) }
                let state: ConversationState
                if item["type"].text == "subAgentActivity" { state = .activity(item) }
                else {
                    let native = item["data"]["agentsStates"][id]
                    // A completed spawn/tool call does not mean the child has completed.
                    state = .status(native["status"].string ?? native.string ?? "", fallback: "已委派")
                }
                values[id] = (agent, state)
            }
        }
        return order.compactMap { values[$0] }
    }
    private func actionLabel(_ state: ConversationState) -> String {
        switch state.label {
        case "已完成": "已结束"
        case "执行中": "正在执行"
        case "失败": "执行失败"
        default: state.label
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if rows.count > 1 {
                let running = rows.filter { $0.state.tone == .active }.count
                Text("\(rows.count) 个 Agent" + (running > 0 ? " · \(running) 个执行中" : "")).font(.caption).foregroundStyle(Design.secondary)
            }
            ForEach(rows, id: \.agent.stableID) { row in
                Button {
                    if let anchorID { model.readingState(for: parentID).anchorID = anchorID }
                    opening = true
                    Task { await model.openSubagent(row.agent["id"].text, parentID: parentID); opening = false }
                } label: {
                    HStack(spacing: 4) {
                        Image("CarryOnLogo").resizable().scaledToFit().frame(width: 14, height: 14)
                        Text(row.agent["title"].text + " " + actionLabel(row.state)).lineLimit(1)
                        Spacer(minLength: 0)
                    }.font(.system(size: 13)).foregroundStyle(row.state.tone == .failure ? .red : Design.secondary).frame(minHeight: 36).contentShape(Rectangle())
                }.buttonStyle(.plain).disabled(opening || model.selectedThread?.id != parentID)
            }
        }
    }
}
