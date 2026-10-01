import Foundation
import CarryOnCore

// AppModel owns state; this boundary owns request identity and delivery reconciliation.
extension AppModel {
    @discardableResult func write(path: String, target: String, body: JSONValue, draftSubmission: Bool = false) async -> Bool {
        guard allowsRequest(path, body: body) else { error = "工作区未授权此操作"; return false }
        guard canWrite else { error = "当前连接不可写，请检查本机授权与连接状态"; return false }
        if target == selectedThread?.id && (conversationReadOnly || (!path.hasSuffix("/compose") && !path.hasSuffix("/session") && !canInteract)) { error = conversationReadOnly ? "此子会话为只读" : "会话尚未就绪"; return false }
        let version = epoch, capturedScope = scope
        var requestID: String?
        writing = true; defer { writing = false }
        do {
            let id = try pending.requestID(scope: capturedScope, target: target, path: path, body: body)
            requestID = id
            let composing = path.hasSuffix("/compose")
            if composing {
                outgoing[id] = .object(["id": .string(id), "threadId": .string(target), "scope": .string(capturedScope),
                    "draftSubmission": .bool(draftSubmission), "prompt": body["prompt"], "created": .number((Date().timeIntervalSince1970 * 1000).rounded()), "state": .string("sending")])
                historyRevision += 1
            }
            var result: JSONValue
            do { result = try await deviceRequest(path, body: body.setting("requestId", .string(id))) }
            catch {
                let rejected = (error as? APIError)?.isWriteRejection == true
                if rejected { try pending.resolve(scope: capturedScope, target: target, requestID: id) }
                if composing, version == epoch, let item = outgoing[id] {
                    outgoing[id] = OutgoingMessageProjection.merge(item, .object(["state": .string(rejected ? "failed" : "uncertain")]))
                }
                throw error
            }
            let deadline = Date().addingTimeInterval(composing ? 120 : 20)
            do {
                while ["preparing", "dispatching"].contains(result["state"].text) ||
                    (path == "/api/threads" && result["state"].text == "accepted" && result["createdThreadId"].string == nil) {
                    guard version == epoch, capturedScope == scope else { return false }
                    guard Date() < deadline else { throw APIError("操作仍在处理，尚未确认结果；原请求已保留，请稍后核对") }
                    try await Task.sleep(for: .milliseconds(300))
                    guard version == epoch, capturedScope == scope else { return false }
                    result = try await deviceRequest("/api/jobs/" + ConsoleAddress.component(id))
                }
            } catch {
                if composing, version == epoch { mergeOutgoing(.object(["id": .string(id), "state": .string("uncertain")])) }
                throw error
            }
            if composing, version == epoch { mergeOutgoing(result.setting("id", .string(id))); reconcileOutgoing() }
            guard version == epoch else { return false }
            try pending.reconcile(scope: capturedScope, job: result.setting("id", .string(id)).setting("threadId", .string(target)))
            let state = result["state"].text
            if ["failed", "interrupted"].contains(state) {
                throw APIError(result["error"].string ?? (state == "interrupted" ? "操作已暂停" : "操作失败"))
            }
            guard ["completed", "accepted", "inProgress"].contains(state) else {
                throw APIError((result["error"].string ?? "操作结果尚未确认") + "；请在请求记录与 Codex App 核对，原请求编号已保留。")
            }
            try pending.resolve(scope: capturedScope, target: target, requestID: id)
            if composing, draftSubmission, let item = outgoing[id] {
                outgoing[id] = item.setting("draftSubmission", .bool(false))
                reconcileOutgoing()
            }
            return true
        } catch {
            // A live native acceptance remains authoritative if the HTTP reply is lost.
            if version == epoch, capturedScope == scope, let id = requestID, let item = outgoing[id],
               ["accepted", "completed", "inProgress"].contains(item["state"].text) {
                try? pending.resolve(scope: capturedScope, target: target, requestID: id)
                outgoing[id] = item.setting("draftSubmission", .bool(false))
                reconcileOutgoing()
                return true
            }
            if version == epoch { report(error, operation: path.hasSuffix("/compose") ? "发送消息" : "提交操作") }
            return false
        }
    }
    func checkOutgoing(_ item: JSONValue) async {
        let capturedScope = scope, identifier = item["id"].text
        guard item["scope"].text == capturedScope, !identifier.isEmpty else { return }
        do {
            let job = try await deviceRequest("/api/jobs/" + ConsoleAddress.component(identifier))
            guard scope == capturedScope, job["id"].text == identifier else { return }
            reconcile([job]); reconcileOutgoing()
            if job["state"].text == "uncertain", outgoing[identifier] != nil {
                error = "尚未找到原生接收凭证，请在 Codex App 核对后，从请求记录标记已核对。此请求不会阻止其他操作。"
            }
        } catch { if scope == capturedScope { report(error, operation: "核对发送结果") } }
    }
    func reconcile(_ jobs: [JSONValue]) {
        for job in jobs { mergeOutgoing(job, live: true) }
        try? pending.reconcile(scope: scope, jobs: jobs)
    }
    var visibleOutgoing: [JSONValue] {
        outgoingFor(selectedThread?.id)
    }
    func outgoingFor(_ threadID: String?) -> [JSONValue] {
        outgoing.values.filter { $0["scope"].text == scope && $0["threadId"].text == threadID &&
            $0["draftSubmission"].bool != true }.sorted { ($0["created"].int ?? 0, $0["id"].text) < ($1["created"].int ?? 0, $1["id"].text) }
    }
    private func mergeOutgoing(_ job: JSONValue, live: Bool = false) {
        let id = job["id"].text
        guard let previous = outgoing[id], previous["scope"].text == scope else { return }
        outgoing[id] = OutgoingMessageProjection.merge(previous, job, live: live)
    }
    func reconcileOutgoing() {
        for snapshot in [history, sideHistory] {
            for item in outgoingFor(snapshot["thread"]["id"].string) {
                if OutgoingMessageProjection.isReflected(item, in: snapshot) { outgoing.removeValue(forKey: item["id"].text) }
            }
        }
    }
    func confirmJob(_ job: JSONValue) async {
        guard canWrite(.send) else { error = "当前无法核对请求结果"; return }
        do {
            if job["state"].text == "uncertain" {
                _ = try await deviceRequest("/api/jobs/\(ConsoleAddress.component(job["id"].text))/acknowledge", body: .object(["confirmed": .bool(true)]))
            }
            try pending.resolve(scope: scope, target: job["threadId"].text, requestID: job["id"].text)
            try pending.resolve(scope: scope, target: "new", requestID: job["id"].text)
            if let project = job["creationProject"]["groupId"].string {
                try pending.resolve(scope: scope, target: "new:" + project, requestID: job["id"].text)
            }
        } catch { report(error, operation: "核对请求结果") }
    }
}
