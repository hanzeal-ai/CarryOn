import SwiftUI
import CarryOnCore

struct ArchiveActionView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let thread: Record
    let scope: String
    let restoring: Bool
    var completed: () -> Void
    @State private var busy = false
    @State private var requestID: String?
    @State private var failure: String?
    @State private var pendingLoaded = false
    private var path: String { "/api/threads/" + ConsoleAddress.component(thread.id) + (restoring ? "/unarchive" : "/archive") }
    private var current: Bool { scope == model.scope && (restoring || model.selectedThread?.id == thread.id) }
    private var title: String { restoring ? "恢复会话" : "归档会话" }
    var body: some View {
        NavigationStack {
            Form {
                Text(thread.title)
                Text(restoring ? "恢复到会话列表，不会自动运行任务。" : "从会话列表移入已归档，保留历史和本地草稿。")
                    .font(.subheadline).foregroundStyle(Design.secondary)
                if let failure { Text(failure).foregroundStyle(.red) }
                if requestID != nil {
                    Button("核对归档结果") { Task { await check() } }.disabled(busy || !current)
                }
            }.navigationTitle(title).navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() }.disabled(busy) }
                    ToolbarItem(placement: .confirmationAction) {
                        Button(busy ? "处理中…" : title) { Task { await submit() } }
                            .disabled(!pendingLoaded || busy || !current || requestID != nil || !model.canWrite(.edit) || (!restoring && (model.state != "idle" || !model.canInteract(.edit))))
                    }
                }
        }.interactiveDismissDisabled(busy)
            .task {
                do {
                    requestID = try model.pending.existingRequestID(scope: scope, target: thread.id, path: path, body: .object([:]))
                    pendingLoaded = true
                } catch { failure = error.localizedDescription }
            }
    }
    private func confirmed(_ job: JSONValue, id: String) -> Bool {
        job["id"].text == id && job["threadId"].text == thread.id && job["state"].text == "completed" &&
        job["result"]["threadId"].text == thread.id && job["result"]["archived"].bool == !restoring
    }
    private func finish() {
        guard current else { return }
        model.workspaceRevision += 1
        if !restoring { model.closeThread() }
        completed(); dismiss()
    }
    private func submit() async {
        guard current, pendingLoaded, !busy, model.canWrite(.edit), requestID == nil,
              restoring || (model.canInteract(.edit) && model.state == "idle" && supportsOperation("archive", in: model.history)) else { return }
        busy = true; failure = nil; defer { busy = false }
        do {
            let id = try model.pending.requestID(scope: scope, target: thread.id, path: path, body: .object([:]))
            requestID = id
            let ok = await model.write(path: path, target: thread.id, body: .object([:])) { job in
                guard job["id"].text == id, job["threadId"].text == thread.id else { failure = "归档凭证身份不匹配"; return }
                if confirmed(job, id: id) { finish() }
            }
            if !ok, current {
                failure = model.error ?? "结果待核对"
                requestID = try model.pending.existingRequestID(scope: scope, target: thread.id, path: path, body: .object([:]))
            }
        } catch { if current { failure = error.localizedDescription } }
    }
    private func check() async {
        guard current, !busy, let id = requestID else { return }
        busy = true; failure = nil; defer { busy = false }
        do {
            let job = try await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id))
            guard current else { return }
            guard job["id"].text == id, job["threadId"].text == thread.id else { throw APIError("归档凭证身份不匹配") }
            if confirmed(job, id: id) {
                try model.pending.reconcile(scope: scope, job: job); finish()
            } else if ["failed", "interrupted", "acknowledged"].contains(job["state"].text) {
                try model.pending.reconcile(scope: scope, job: job); requestID = nil
                failure = job["error"].string ?? "操作未完成"
            } else { failure = job["error"].string ?? "结果仍待核对，原请求已保留" }
        } catch { if current { failure = error.localizedDescription } }
    }
}

struct ArchivedThreadsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var records: [Record] = []
    @State private var search = ""
    @State private var offset = 0
    @State private var more = false
    @State private var loading = false
    @State private var failure: String?
    @State private var canRestore = false
    @State private var selected: Record?
    @State private var selectedScope = ""
    @State private var revision = 0
    @State private var requestVersion = UUID()
    var body: some View {
        NavigationStack {
            List {
                if let failure { Text(failure).foregroundStyle(.red); Button("重试") { Task { await load(reset: true) } } }
                if records.isEmpty, !loading, failure == nil { Text("暂无已归档会话").foregroundStyle(Design.secondary) }
                ForEach(records) { record in
                    Button { selectedScope = model.scope; selected = record } label: {
                        HStack(spacing: 13) {
                            SymbolTile(name: "archivebox", color: Design.secondary)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(record.title).font(.body.weight(.medium)).lineLimit(2)
                                Text(record.value["cwd"].text).font(.caption).foregroundStyle(Design.secondary).lineLimit(1)
                            }
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
                        }.padding(.vertical, 8).contentShape(Rectangle())
                    }
                        .buttonStyle(.plain).disabled(!canRestore || !model.canWrite(.edit))
                }
                if more { Button("加载更多") { Task { await load(reset: false) } }.disabled(loading) }
                if loading { ProgressView() }
            }.navigationTitle("已归档").navigationBarTitleDisplayMode(.inline)
                .searchable(text: $search, prompt: "搜索已归档会话")
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("完成") { dismiss() } } }
                .refreshable { await load(reset: true) }
                .task(id: model.scope + "\n" + search + "\n" + String(revision)) { await load(reset: true) }
                .sheet(item: $selected) { record in
                    ArchiveActionView(thread: record, scope: selectedScope, restoring: true) { selected = nil; revision += 1 }
                }
        }
    }
    private func load(reset: Bool) async {
        if !reset && loading { return }
        let version = UUID(), scope = model.scope, query = search
        requestVersion = version; loading = true; failure = nil
        if reset { records = []; offset = 0; more = false; canRestore = false }
        defer { if requestVersion == version { loading = false } }
        do {
            if reset { try await Task.sleep(for: .milliseconds(180)) }
            let response = try await model.deviceRequest("/api/archived?limit=100&offset=\(reset ? 0 : offset)&search=" + ConsoleAddress.component(query))
            guard !Task.isCancelled, scope == model.scope, query == search, requestVersion == version else { return }
            guard case .array(let rows) = response["threads"], let next = response["nextOffset"].int, next >= 0, response["supportsRestore"].bool != nil else { throw APIError("归档列表数据格式不正确") }
            let incoming = try rows.map(Record.init)
            var seen = Set(records.map(\.id)); records.append(contentsOf: incoming.filter { seen.insert($0.id).inserted })
            offset = next; more = incoming.count == 100
            canRestore = response["supportsRestore"].bool == true
        } catch { if !Task.isCancelled, scope == model.scope, requestVersion == version { failure = error.localizedDescription } }
    }
}
