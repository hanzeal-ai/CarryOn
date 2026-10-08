import SwiftUI
import CarryOnCore

struct ConversationSearchView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var rows: [JSONValue] = []
    @State private var thread: Record?
    @State private var cursor: String?
    @State private var loading = false
    @State private var failure: String?
    @State private var version = UUID()
    private var identity: String { model.scope + "\n" + query + "\n" + (thread?.id ?? "") }
    private var allowed: Bool { model.authenticated && model.connected && model.allows(.view) && model.status["supportsFullTextSearch"].bool == true }
    var body: some View {
        NavigationStack {
            List {
                if loading && rows.isEmpty { ProgressView() }
                if let failure { Button(failure + " · 重试") { Task { await load() } }.foregroundStyle(.red) }
                if !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !loading && rows.isEmpty && failure == nil {
                    Text("没有匹配的消息").foregroundStyle(Design.secondary)
                }
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    Button {
                        guard allowed else { return }
                        if let thread {
                            let capturedScope = model.scope
                            Task { do { try await model.openSearchOccurrence(thread, occurrence: row) } catch { if capturedScope == model.scope && model.allows(.view) { model.report(error, operation: "定位搜索消息", blocking: false) } } }
                            dismiss()
                        }
                        else if let record = try? Record(row) { thread = record }
                    } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(thread == nil ? row["title"].text : "打开会话").font(.body)
                            Text(highlighted(row)).font(.subheadline).foregroundStyle(Design.secondary)
                        }.padding(.vertical, 6)
                    }.buttonStyle(.plain)
                }
                if cursor != nil { Button("加载更多") { Task { await load(more: true) } }.disabled(loading) }
            }
            .searchable(text: $query, prompt: "搜索消息内容")
            .navigationTitle(thread?.title ?? "搜索会话内容").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { if thread != nil { Button("返回结果") { thread = nil } } }
                ToolbarItem(placement: .confirmationAction) { Button("关闭") { dismiss() } }
            }
            .task(id: identity) { await load(debounce: true) }
            .onChange(of: model.scope) { _, _ in query = ""; thread = nil; rows = []; cursor = nil; version = UUID() }
            .onChange(of: allowed) { _, value in if !value { rows = []; cursor = nil; version = UUID(); dismiss() } }
            .onDisappear { version = UUID() }
        }
    }
    private func highlighted(_ row: JSONValue) -> AttributedString {
        let snippet = row["snippet"].text
        var text = AttributedString(snippet)
        if let start = row["snippetMatchRange"]["start"].int, let end = row["snippetMatchRange"]["end"].int,
           start >= 0, end > start, end <= (snippet as NSString).length,
           let range = Range(NSRange(location: start, length: end - start), in: snippet),
           let lower = AttributedString.Index(range.lowerBound, within: text), let upper = AttributedString.Index(range.upperBound, within: text) {
            text[lower..<upper].backgroundColor = Color.yellow.opacity(0.3)
        }
        return text
    }
    private func load(more: Bool = false, debounce: Bool = false) async {
        let scope = model.scope, target = thread?.id, term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let token = UUID(); version = token
        if !more { rows = []; cursor = nil }
        failure = nil; loading = true
        defer { if version == token { loading = false } }
        guard allowed, !term.isEmpty else { return }
        guard term.unicodeScalars.count <= 200 else { failure = "最多输入 200 个字符"; return }
        do {
            if debounce { try await Task.sleep(for: .milliseconds(250)) }
            let path = target.map { "/api/threads/\(ConsoleAddress.component($0))/search" } ?? "/api/search"
            let value = try await model.deviceRequest(path + "?search=\(ConsoleAddress.component(term))&limit=30" + (more ? cursor.map { "&cursor=\(ConsoleAddress.component($0))" } ?? "" : ""))
            guard !Task.isCancelled, allowed, scope == model.scope, target == thread?.id, version == token else { return }
            guard case .array(let incoming) = value[target == nil ? "threads" : "occurrences"] else { throw APIError("搜索回执格式无效") }
            rows = more ? rows + incoming : incoming; cursor = value["nextCursor"].string
        } catch {
            guard !Task.isCancelled, allowed, scope == model.scope, version == token else { return }
            failure = error.localizedDescription
        }
    }
}
