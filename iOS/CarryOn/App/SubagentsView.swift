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
                        HStack { Text(thread.title); Spacer(); if thread.value["access"]["canInteract"].bool != true { Text("只读").font(.caption).foregroundStyle(Design.secondary) } }
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
                Label(agent["title"].text, systemImage: "person.crop.circle")
                    .font(.caption).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
            }.buttonStyle(.plain).foregroundStyle(Design.link).disabled(opening)
        }
        }
    }
}
