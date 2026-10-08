import SwiftUI
import CarryOnCore

struct BackgroundTerminalsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let thread: Record
    let scope: String
    @State private var rows: [Record] = []
    @State private var cursor: String?
    @State private var cursors = Set<String>()
    @State private var busy = false
    @State private var loaded = false
    @State private var failure: String?
    @State private var readFailure: String?
    @State private var requestID: String?
    @State private var cleanConfirmation = false
    private var target: String { "terminal:" + thread.id }
    private var path: String { "/api/threads/" + ConsoleAddress.component(thread.id) + "/terminals" }
    private var current: Bool { model.scope == scope && model.selectedThread?.id == thread.id && model.allows(.view) }
    private var canStop: Bool { current && model.canInteract(.stop) && model.history["controls"]["supportsBackgroundTerminals"].bool == true }
    var body: some View {
        NavigationStack {
            List {
                ForEach(rows) { row in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(row.value["command"].text).font(.system(.body, design: .monospaced)).textSelection(.enabled)
                        Text(row.value["cwd"].text).font(.caption).foregroundStyle(Design.secondary).textSelection(.enabled)
                        Button("停止", role: .destructive) { Task { await stop(.object(["action": .string("terminate"), "processId": .string(row.id)])) } }.disabled(busy || requestID != nil || !canStop)
                    }.padding(.vertical, 4)
                }
                if loaded && rows.isEmpty && failure == nil && readFailure == nil { Text("没有运行中的后台终端").foregroundStyle(Design.secondary) }
                if let readFailure { Text(readFailure).foregroundStyle(Design.secondary) }
                if let failure { Text(failure).foregroundStyle(Design.secondary) }
                Button(loaded ? "刷新" : "重新读取") { Task { await load() } }.disabled(busy)
                if cursor != nil { Button("加载更多") { Task { await load(more: true) } }.disabled(busy) }
                if requestID != nil { Button("核对原请求") { Task { await check() } }.disabled(busy) }
            }.navigationTitle("后台终端").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() }.disabled(busy) }
                    ToolbarItem(placement: .confirmationAction) { Button("全部停止", role: .destructive) { cleanConfirmation = true }.disabled(busy || !loaded || rows.isEmpty || requestID != nil || !canStop) }
                }
        }.interactiveDismissDisabled(busy)
            .confirmationDialog("停止此会话的所有后台终端？", isPresented: $cleanConfirmation, titleVisibility: .visible) { Button("全部停止", role: .destructive) { Task { await stop(.object(["action": .string("clean")])) } } }
            .onChange(of: current) { _, value in if !value { rows = []; dismiss() } }
            .task { await restore(); await load() }
    }
    private func load(more: Bool = false) async {
        guard current, !busy, !more || cursor != nil else { return }
        busy = true; defer { busy = false }
        do {
            let value = try await model.deviceRequest(path + "?limit=50" + (more ? "&cursor=" + ConsoleAddress.component(cursor!) : ""))
            guard current, !Task.isCancelled else { return }
            guard value["threadId"].text == thread.id, case .array(let items) = value["terminals"], value.object?.keys.contains("nextCursor") == true, value["nextCursor"] == .null || value["nextCursor"].string?.isEmpty == false else { throw APIError("终端列表格式不正确") }
            let records = try items.map(Record.init)
            guard Set(records.map(\.id)).count == records.count, records.allSatisfy({ !$0.id.isEmpty && $0.value["processId"].text == $0.id && $0.value["command"].string != nil && $0.value["cwd"].string != nil }), !more || !records.contains(where: { row in rows.contains(where: { $0.id == row.id }) }) else { throw APIError("终端身份重复或无效") }
            if !more { cursors = [] }
            if let next = value["nextCursor"].string { guard !cursors.contains(next) else { throw APIError("终端分页游标重复") }; cursors.insert(next) }
            rows = more ? rows + records : records; cursor = value["nextCursor"].string; loaded = true; readFailure = nil
        } catch { if current { readFailure = error.localizedDescription } }
    }
    private func reconcile(_ job: JSONValue, id: String) throws {
        guard current else { return }
        let receipt = try TerminalReceipt(job)
        guard receipt.threadID == thread.id, job["id"].text == id, try model.pending.existingRequestID(scope: scope, target: target, path: receipt.path, body: receipt.body) == id else { throw APIError("终端凭证身份不匹配，原请求已保留") }
        try model.pending.reconcile(scope: scope, job: job)
        if receipt.completed { requestID = nil; failure = nil }
        else if ["failed", "interrupted", "acknowledged"].contains(job["state"].text) { requestID = nil; failure = job["error"].string ?? "操作未完成" }
        else { failure = job["error"].string ?? "结果待核对，原请求已保留" }
    }
    private func restore() async {
        guard current else { return }
        do { for id in try model.pending.requestIDs(scope: scope, target: target) { requestID = id; try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id); if requestID != nil { break } } }
        catch { if current { failure = error.localizedDescription } }
    }
    private func check() async {
        guard current, !busy, let id = requestID else { return }
        busy = true
        do { try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id) } catch { if current { failure = error.localizedDescription } }
        busy = false
        if requestID == nil { await load() }
    }
    private func stop(_ body: JSONValue) async {
        guard current, !busy, requestID == nil, canStop, loaded else { return }
        if body["action"].text == "terminate" { guard rows.contains(where: { $0.id == body["processId"].text }) else { return } }
        busy = true; failure = nil; var admitted = false
        do {
            let id = try model.pending.requestID(scope: scope, target: target, path: path, body: body); requestID = id
            var job = try await model.deviceRequest(path, body: body.setting("requestId", .string(id))); admitted = true
            for _ in 0..<60 where ["preparing", "dispatching"].contains(job["state"].text) { guard current else { busy = false; return }; try await Task.sleep(for: .milliseconds(300)); job = try await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)) }
            try reconcile(job, id: id)
        } catch { if current { if !admitted, (error as? APIError)?.isWriteRejection == true, let id = requestID { try? model.pending.resolve(scope: scope, target: target, requestID: id); requestID = nil }; failure = error.localizedDescription } }
        busy = false
        if requestID == nil && failure == nil { await load() }
    }
}
