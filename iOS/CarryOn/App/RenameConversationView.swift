import SwiftUI
import CarryOnCore

struct RenameConversationView: View {
    @Environment(AppModel.self) private var model
    @State private var finished = false
    @State private var prompting = false
    @State private var recovering = false
    let thread: Record
    let scope: String
    var onClose: () -> Void = {}
    @State private var name = ""
    @State private var requestID: String?
    @State private var loaded = false
    @State private var busy = false
    @State private var failure: String?
    private var path: String { "/api/threads/" + ConsoleAddress.component(thread.id) + "/rename" }
    private var current: Bool { model.scope == scope && model.selectedThread?.id == thread.id }
    private var normalized: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var allowed: Bool { current && model.canInteract(.edit) && supportsOperation("rename", in: model.history) }
    var body: some View {
        Color.clear.frame(width: 0, height: 0)
            .alert("重命名任务", isPresented: $prompting) {
                TextField("会话名称", text: $name)
                Button("取消", role: .cancel) { onClose() }
                Button("保存") { Task { await save() } }
                    .disabled(!loaded || busy || requestID != nil || !allowed || normalized.isEmpty || normalized.unicodeScalars.count > 200)
            }
            .sheet(isPresented: $recovering, onDismiss: onClose) {
                NavigationStack {
                    Form {
                        TextField("会话名称", text: $name).disabled(busy || requestID != nil || !loaded)
                            .accessibilityLabel("会话名称")
                        if let failure { Text(failure).foregroundStyle(.red) }
                        if !loaded, failure != nil { Button("重新读取待处理请求") { Task { await restore() } }.disabled(busy || !current) }
                        if requestID != nil { Button("核对重命名结果") { Task { await check() } }.disabled(busy || !current) }
                    }.navigationTitle("重命名").navigationBarTitleDisplayMode(.inline)
                        .toolbar {
                            ToolbarItem(placement: .cancellationAction) { Button("关闭") { recovering = false }.disabled(busy) }
                            ToolbarItem(placement: .confirmationAction) {
                                Button("保存") { Task { await save() } }
                                    .disabled(!loaded || busy || requestID != nil || !allowed || normalized.isEmpty || normalized.unicodeScalars.count > 200)
                            }
                        }
                }.interactiveDismissDisabled(busy)
            }
            .task { await restore() }
            .onChange(of: current) { _, value in if !value { prompting = false; recovering = false; onClose() } }
    }
    private func restore() async {
        guard current, !busy else { return }
        busy = true; failure = nil; defer {
            busy = false
            if current && !finished {
                if failure != nil || requestID != nil { recovering = true }
                else if !recovering { prompting = true }
            }
        }
            name = model.history["thread"]["title"].string ?? thread.title
            do {
                let ids = try model.pending.requestIDs(scope: scope, target: thread.id)
                for id in ids {
                    let job = try await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id))
                    guard current else { return }
                    guard job["id"].text == id, job["threadId"].text == thread.id else { throw APIError("待处理请求身份不匹配，请核对请求记录") }
                    if job["kind"].text == "rename" {
                        guard let pendingName = job["name"].string, !pendingName.isEmpty else { throw APIError("待处理重命名内容无法读取，请核对请求记录") }
                        guard try model.pending.existingRequestID(scope: scope, target: thread.id, path: path, body: .object(["name": .string(pendingName)])) == id else { throw APIError("待处理重命名内容身份不匹配，原请求已保留") }
                        requestID = id; name = pendingName
                        try reconcile(job, id: id); break
                    }
                }
                loaded = true
            } catch { if current { failure = error.localizedDescription } }
    }
    private func finish() {
        guard current else { return }
        finished = true
        model.selectedThread = try? Record(thread.value.setting("title", .string(normalized)))
        model.workspaceRevision += 1; model.retryHistory(); prompting = false; recovering = false; onClose()
    }
    private func reconcile(_ job: JSONValue, id: String) throws {
        guard current else { return }
        guard job["id"].text == id, job["threadId"].text == thread.id, job["kind"].text == "rename", job["name"].text == normalized else { throw APIError("重命名凭证或内容身份不匹配，原请求已保留") }
        if job["state"].text == "completed", job["result"]["threadId"].text == thread.id, job["result"]["name"].text == normalized {
            try model.pending.reconcile(scope: scope, job: job); finish()
        } else if ["failed", "interrupted", "acknowledged"].contains(job["state"].text) {
            try model.pending.reconcile(scope: scope, job: job); requestID = nil; failure = job["error"].string ?? "重命名未完成"
        } else { failure = job["error"].string ?? "结果仍待核对，原请求已保留" }
    }
    private func save() async {
        guard loaded, !busy, requestID == nil, allowed, !normalized.isEmpty, normalized.unicodeScalars.count <= 200 else { return }
        prompting = false
        busy = true; failure = nil; defer { busy = false; if current && !finished && (failure != nil || requestID != nil) { recovering = true } }
        let body = JSONValue.object(["name": .string(normalized)])
        do {
            requestID = try model.pending.requestID(scope: scope, target: thread.id, path: path, body: body)
            if await model.write(path: path, target: thread.id, body: body) { finish() }
            else if current { requestID = try model.pending.existingRequestID(scope: scope, target: thread.id, path: path, body: body); failure = model.error }
        } catch { if current { failure = error.localizedDescription } }
    }
    private func check() async {
        guard current, !busy, let id = requestID else { return }
        busy = true; defer { busy = false }
        do { try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id) }
        catch { if current { failure = error.localizedDescription } }
    }
}
