import SwiftUI
import CarryOnCore

struct SectionManagementView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let section: Record?
    let scope: String
    let completed: () -> Void
    var movingThread: Record? = nil
    @State private var name = ""
    @State private var orderPage = NativeSectionPage()
    @State private var beforeThread: String?
    @State private var orderLoaded = false
    @State private var busy = false
    @State private var requestID: String?
    @State private var failure: String?
    @State private var confirmDelete = false
    private var current: Bool { model.scope == scope && model.allows(.view) && model.status["supportsThreadSections"].bool == true }
    var body: some View {
        NavigationStack {
            Form {
                if let movingThread {
                    Picker("排在会话之前", selection: $beforeThread) {
                        Text("末尾").tag(String?.none)
                        ForEach(orderPage.rows.filter { $0.id != movingThread.id }) { thread in Text(thread.title).tag(Optional(thread.id)) }
                    }.disabled(busy || requestID != nil || !orderLoaded)
                    if orderPage.cursor != nil { Button("加载更多会话") { Task { await loadOrder(more: true) } }.disabled(busy || orderPage.busy) }
                    if let error = orderPage.failure { Text(error).foregroundStyle(Design.secondary); Button("重试") { Task { await loadOrder() } } }
                } else { TextField("分组名称", text: $name).disabled(busy || requestID != nil) }
                if let failure { Text(failure).foregroundStyle(Design.secondary) }
                if requestID != nil { Button("核对原请求") { Task { await check() } }.disabled(busy || !current) }
                if section != nil, movingThread == nil { Button("删除分组", role: .destructive) { confirmDelete = true }.disabled(busy || requestID != nil || !current || !model.canWrite(.edit)) }
            }.navigationTitle(movingThread != nil ? "调整顺序" : section == nil ? "新建分组" : "编辑分组").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() }.disabled(busy) }
                    ToolbarItem(placement: .confirmationAction) { Button("保存") { Task { await submit(delete: false) } }.disabled(busy || requestID != nil || (movingThread == nil ? name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty : !orderLoaded) || !current || !model.canWrite(.edit)) }
                }
        }.interactiveDismissDisabled(busy)
            .confirmationDialog("删除此分组？其中的会话会保留。", isPresented: $confirmDelete, titleVisibility: .visible) { Button("删除分组", role: .destructive) { Task { await submit(delete: true) } } }
            .onChange(of: current) { _, value in if !value { orderPage.reset(); name = ""; dismiss() } }
            .task { name = section?.title ?? ""; await restore(); if movingThread != nil { await loadOrder() } }
    }
    private func loadOrder(more: Bool = false) async {
        guard current, let section else { return }
        await orderPage.load(model, path: "/api/sections/" + ConsoleAddress.component(section.id) + "/threads", key: "threads", more: more)
        if current, orderPage.failure == nil { orderLoaded = true }
    }
    private func reconcile(_ job: JSONValue, id: String) throws {
        guard current else { return }
        let receipt = try SectionReceipt(job)
        guard job["id"].text == id, try model.pending.existingRequestID(scope: scope, target: "sections", path: receipt.path, body: receipt.body) == id else { throw APIError("分组管理凭证身份不匹配，原请求已保留") }
        try model.pending.reconcile(scope: scope, job: job)
        if receipt.completed { model.workspaceRevision += 1; completed(); dismiss() }
        else if ["failed", "interrupted", "acknowledged"].contains(job["state"].text) { requestID = nil; failure = job["error"].string ?? "操作未完成" }
        else { failure = job["error"].string ?? "结果待核对，原请求已保留" }
    }
    private func restore() async {
        guard current, !busy else { return }
        busy = true; defer { busy = false }
        do {
            for id in try model.pending.requestIDs(scope: scope, target: "sections") {
                requestID = id
                try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id)
                if requestID != nil { break }
            }
        } catch { if current { failure = error.localizedDescription } }
    }
    private func submit(delete: Bool) async {
        guard current, model.canWrite(.edit), !busy, requestID == nil else { return }
        let title = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard movingThread != nil || delete || !title.isEmpty, !delete || section != nil else { return }
        if movingThread != nil { guard section != nil, orderLoaded, beforeThread == nil || orderPage.rows.contains(where: { $0.id == beforeThread }) else { return } }
        let path = section.map { "/api/sections/" + ConsoleAddress.component($0.id) } ?? "/api/sections"
        let body: JSONValue = movingThread.map { .object(["action": .string("order"), "threadId": .string($0.id), "beforeThreadId": beforeThread.map(JSONValue.string) ?? .null]) } ?? .object(section == nil ? ["name": .string(title)] : delete ? ["action": .string("delete")] : ["action": .string("update"), "name": .string(title)])
        busy = true; failure = nil; defer { busy = false }
        var admitted = false
        do {
            requestID = try model.pending.requestID(scope: scope, target: "sections", path: path, body: body)
            let id = requestID!
            var job = try await model.deviceRequest(path, body: body.setting("requestId", .string(id)))
            admitted = true
            for _ in 0..<60 where ["preparing", "dispatching"].contains(job["state"].text) {
                guard current else { return }; try await Task.sleep(for: .milliseconds(300))
                job = try await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id))
            }
            try reconcile(job, id: id)
        } catch {
            if current {
                if !admitted, (error as? APIError)?.isWriteRejection == true, let id = requestID {
                    try? model.pending.resolve(scope: scope, target: "sections", requestID: id); requestID = nil
                }
                failure = error.localizedDescription
            }
        }
    }
    private func check() async {
        guard current, !busy, let id = requestID else { return }
        busy = true; defer { busy = false }
        do { try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id) }
        catch { if current { failure = error.localizedDescription } }
    }
}
