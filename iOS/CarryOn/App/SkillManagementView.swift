import SwiftUI
import CarryOnCore

struct SkillManagementView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let thread: Record
    let scope: String
    @State private var rows: [JSONValue] = []
    @State private var busy = false
    @State private var loaded = false
    @State private var failure: String?
    @State private var readFailure: String?
    @State private var requestID: String?
    private var current: Bool { model.scope == scope && model.selectedThread?.id == thread.id && model.allows(.view) }
    private var editable: Bool { current && model.canInteract(.edit) && model.history["controls"]["supportsSkills"].bool == true && !model.pending.hasPending(scope: scope, target: "plugin-management") }
    private var path: String { "/api/threads/" + ConsoleAddress.component(thread.id) + "/skills/config" }
    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(rows, id: \.stableID) { skill in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(skill["interface"]["displayName"].string ?? skill["name"].text).font(.headline)
                            if let description = skill["interface"]["shortDescription"].string ?? skill["description"].string { Text(description).font(.caption).foregroundStyle(Design.secondary) }
                            Text(skill["enabled"].bool == true ? "已启用" : "已停用").font(.caption).foregroundStyle(Design.secondary)
                            Button(skill["enabled"].bool == true ? "停用" : "启用") { Task { await submit(skill) } }.disabled(busy || requestID != nil || !editable)
                        }.padding(.vertical, 4)
                    }
                    if loaded && rows.isEmpty { Text("当前项目没有技能").foregroundStyle(Design.secondary) }
                } footer: { Text("启用状态保存在此工作区，并影响使用该技能的会话。") }
                if let readFailure { Text(readFailure).foregroundStyle(Design.secondary) }
                if let failure { Text(failure).foregroundStyle(Design.secondary) }
                Button("刷新") { Task { await load() } }.disabled(busy)
                if requestID != nil { Button("核对原请求") { Task { await check() } }.disabled(busy) }
            }.navigationTitle("管理技能").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() }.disabled(busy) } }
        }.interactiveDismissDisabled(busy)
            .onChange(of: current) { _, value in if !value { rows = []; dismiss() } }
            .task { await restore(); await load() }
    }
    private func load() async {
        guard current, !busy else { return }; busy = true; defer { busy = false }
        do {
            let page = try await model.deviceRequest("/api/threads/" + ConsoleAddress.component(thread.id) + "/skills")
            guard current, !Task.isCancelled else { return }
            guard case .array(let items) = page["skills"], items.allSatisfy({ $0["path"].string?.isEmpty == false && $0["name"].string?.isEmpty == false && $0["enabled"].bool != nil }), Set(items.map { $0["path"].text }).count == items.count else { throw APIError("技能目录格式无效") }
            rows = items; loaded = true; readFailure = page["errors"].array.isEmpty ? nil : page["errors"].array.map { $0["message"].text }.joined(separator: "\n")
        } catch { if current { readFailure = error.localizedDescription } }
    }
    private func reconcile(_ job: JSONValue, id: String) throws {
        guard current else { return }; let receipt = try SkillConfigurationReceipt(job)
        guard job["id"].text == id, try model.pending.existingRequestID(scope: scope, target: "skill-config", path: receipt.path, body: receipt.body) == id else { throw APIError("技能配置凭证身份不匹配，原请求已保留") }
        try model.pending.reconcile(scope: scope, job: job)
        if receipt.completed { requestID = nil; failure = nil }
        else if ["failed", "interrupted", "acknowledged"].contains(job["state"].text) { requestID = nil; failure = job["error"].string ?? "配置未完成" }
        else { failure = job["error"].string ?? "结果待核对，原请求已保留" }
    }
    private func restore() async {
        guard current else { return }
        do { for id in try model.pending.requestIDs(scope: scope, target: "skill-config") { requestID = id; try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id); if requestID != nil { break } } }
        catch { if current { failure = error.localizedDescription } }
    }
    private func check() async {
        guard current, !busy, let id = requestID else { return }; busy = true
        do { try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id) } catch { if current { failure = error.localizedDescription } }
        busy = false; if requestID == nil { await load() }
    }
    private func submit(_ skill: JSONValue) async {
        guard editable, !busy, requestID == nil, rows.contains(skill), let enabled = skill["enabled"].bool else { return }
        let body: JSONValue = .object(["path": skill["path"], "enabled": .bool(!enabled)])
        busy = true; failure = nil; var admitted = false
        do {
            let id = try model.pending.requestID(scope: scope, target: "skill-config", path: path, body: body); requestID = id
            var job = try await model.deviceRequest(path, body: body.setting("requestId", .string(id))); admitted = true
            for _ in 0..<60 where ["preparing", "dispatching"].contains(job["state"].text) { guard current else { busy = false; return }; try await Task.sleep(for: .milliseconds(300)); job = try await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)) }
            try reconcile(job, id: id)
        } catch { if current { if !admitted, (error as? APIError)?.isWriteRejection == true, let id = requestID { try? model.pending.resolve(scope: scope, target: "skill-config", requestID: id); requestID = nil }; failure = error.localizedDescription } }
        busy = false; if requestID == nil { await load() }
    }
}
