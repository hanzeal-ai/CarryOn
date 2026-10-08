import SwiftUI
import CarryOnCore

struct SectionConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let thread: Record
    let scope: String
    @State private var sections: [Record] = []
    @State private var cursor: String?
    @State private var destination: String?
    @State private var requestID: String?
    @State private var loaded = false
    @State private var busy = false
    @State private var failure: String?
    private var path: String { "/api/threads/" + ConsoleAddress.component(thread.id) + "/section" }
    private var current: Bool { model.scope == scope && model.selectedThread?.id == thread.id && model.allows(.view) && model.status["supportsThreadSections"].bool == true }
    private var bodyValue: JSONValue { .object(["sectionId": destination.map(JSONValue.string) ?? .null]) }
    private var destinationLoaded: Bool { destination == nil || sections.contains { $0.id == destination } }
    var body: some View {
        NavigationStack {
            Form {
                Picker("分组", selection: $destination) {
                    Text("未分组").tag(String?.none)
                    ForEach(sections) { section in Text(section.value["pinned"].bool == true ? "置顶" : section.title).tag(Optional(section.id)) }
                }.disabled(busy || requestID != nil || !loaded)
                if !destinationLoaded { Text("当前分组尚未载入，请加载更多分组").foregroundStyle(Design.secondary) }
                if cursor != nil { Button("加载更多分组") { Task { await loadMore() } }.disabled(busy || !current) }
                if let failure { Text(failure).foregroundStyle(.red) }
                if !loaded, !busy { Button("重新读取") { Task { await restore() } } }
                if requestID != nil { Button("核对分组移动结果") { Task { await check() } }.disabled(busy || !current) }
            }.navigationTitle("移动到分组").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() }.disabled(busy) }
                    ToolbarItem(placement: .confirmationAction) { Button("保存") { Task { await save() } }.disabled(!loaded || !destinationLoaded || busy || requestID != nil || !current || !model.canWrite(.edit)) }
                }
        }.interactiveDismissDisabled(busy).onChange(of: current) { _, value in if !value { sections = []; dismiss() } }.task { await restore() }
    }
    private func loadPage(_ next: String?) async throws {
        let result = try await model.deviceRequest("/api/sections?limit=50" + (next.map { "&cursor=" + ConsoleAddress.component($0) } ?? ""))
        guard current else { return }
        let rows = try result["sections"].array.map(Record.init)
        sections = next == nil ? rows : sections + rows.filter { row in !sections.contains { $0.id == row.id } }
        cursor = result["nextCursor"].string
    }
    private func loadMore() async {
        guard current, !busy, let cursor else { return }
        busy = true; defer { busy = false }
        do { try await loadPage(cursor) } catch { if current { failure = error.localizedDescription } }
    }
    private func restore() async {
        guard current, !busy else { return }
        busy = true; failure = nil; defer { busy = false }
        do {
            try await loadPage(nil)
            let membership = try await model.deviceRequest(path)
            guard current else { return }
            guard membership["threadId"].text == thread.id, membership.object?.keys.contains("sectionId") == true,
                  membership["sectionId"] == .null || membership["sectionId"].string != nil else { throw APIError("分组归属回执不匹配") }
            destination = membership["sectionId"].string
            for id in try model.pending.requestIDs(scope: scope, target: thread.id) {
                let job = try await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id))
                guard current else { return }
                guard job["id"].text == id, job["threadId"].text == thread.id else { throw APIError("待处理请求身份不匹配") }
                if job["kind"].text == "section-move" {
                    guard job.object?.keys.contains("sectionId") == true,
                          job["sectionId"] == .null || job["sectionId"].string != nil else { throw APIError("原分组内容无法读取") }
                    destination = job["sectionId"].string
                    guard try model.pending.existingRequestID(scope: scope, target: thread.id, path: path, body: bodyValue) == id else { throw APIError("原分组内容身份不匹配") }
                    requestID = id; try reconcile(job, id: id); break
                }
            }
            loaded = true
        } catch { if current { failure = error.localizedDescription } }
    }
    private func finish() { if current { model.workspaceRevision += 1; dismiss() } }
    private func reconcile(_ job: JSONValue, id: String) throws {
        guard current else { return }
        guard job["id"].text == id, job["threadId"].text == thread.id, job["kind"].text == "section-move",
              job.object?.keys.contains("sectionId") == true, job["sectionId"] == bodyValue["sectionId"] else { throw APIError("分组凭证身份不匹配，原请求已保留") }
        if job["state"].text == "completed", job["result"]["threadId"].text == thread.id,
           job["result"].object?.keys.contains("sectionId") == true, job["result"]["sectionId"] == bodyValue["sectionId"] {
            try model.pending.reconcile(scope: scope, job: job); finish()
        } else if ["failed", "interrupted", "acknowledged"].contains(job["state"].text) {
            try model.pending.reconcile(scope: scope, job: job); requestID = nil; failure = job["error"].string ?? "分组移动未完成"
        } else { failure = job["error"].string ?? "结果仍待核对，原请求已保留" }
    }
    private func save() async {
        guard loaded, destinationLoaded, current, !busy, requestID == nil, model.canWrite(.edit) else { return }
        busy = true; failure = nil; defer { busy = false }
        do {
            requestID = try model.pending.requestID(scope: scope, target: thread.id, path: path, body: bodyValue)
            if await model.write(path: path, target: thread.id, body: bodyValue) { finish() }
            else if current { requestID = try model.pending.existingRequestID(scope: scope, target: thread.id, path: path, body: bodyValue); failure = model.error }
        } catch { if current { failure = error.localizedDescription } }
    }
    private func check() async {
        guard current, !busy, let id = requestID else { return }
        busy = true; defer { busy = false }
        do { try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id) }
        catch { if current { failure = error.localizedDescription } }
    }
}
