import SwiftUI
import CarryOnCore

struct PluginManagementView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let thread: Record
    let scope: String
    @State private var rows: [JSONValue] = []
    @State private var detail: JSONValue?
    @State private var busy = false
    @State private var loaded = false
    @State private var failure: String?
    @State private var readFailure: String?
    @State private var requestID: String?
    @State private var confirmAction = false
    @State private var search = ""
    @State private var searchMode = "directory"
    @State private var resultsTerm = ""
    @State private var nextCursor: String?
    @State private var seenCursors: Set<String> = []
    private var filteredRows: [JSONValue] {
        let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
        return searchMode != "directory" || query.isEmpty ? rows : rows.filter {
            [$0["name"].text, $0["interface"]["displayName"].text, $0["marketplaceName"].text]
                .contains { $0.localizedStandardContains(query) }
        }
    }
    private var path: String { "/api/threads/" + ConsoleAddress.component(thread.id) + "/plugins" }
    private var current: Bool { model.scope == scope && model.selectedThread?.id == thread.id && model.allows(.view) && model.status["supportsPluginManagement"].bool == true }
    private var editable: Bool { current && model.canWrite(.edit) && !model.conversationReadOnly && !model.pending.hasPending(scope: scope, target: "skill-config") }
    var body: some View {
        NavigationStack {
            List {
                if let detail {
                    let plugin = detail["summary"], installed = plugin["installed"].bool == true
                    Section {
                        Text(plugin["interface"]["displayName"].string ?? plugin["name"].text).font(.headline)
                        if let description = detail["description"].string { Text(description) }
                        Text(detail["marketplaceName"].text).font(.caption).foregroundStyle(Design.secondary)
                        if let source = plugin["source"].object {
                            if let type = source["type"]?.string { Text("来源 · " + type).font(.caption).foregroundStyle(Design.secondary) }
                            ForEach(["path", "url", "package", "registry", "refName", "version"], id: \.self) { key in
                                if let value = source[key]?.string, !value.isEmpty { Text(value).font(.caption).foregroundStyle(Design.secondary).textSelection(.enabled) }
                            }
                        }
                        Text(installed ? "已安装" : "未安装").foregroundStyle(Design.secondary)
                        ForEach(detail["skills"].array, id: \.stableID) { Text("技能 · " + $0["name"].text) }
                        ForEach(detail["mcpServers"].array, id: \.stableID) { Text("MCP · " + $0.text) }
                        ForEach(detail["apps"].array, id: \.stableID) { Text("应用 · " + $0["name"].text) }
                        if !detail["hooks"].array.isEmpty { Text("包含运行钩子").foregroundStyle(Design.secondary) }
                        Button(installed ? "卸载插件" : "安装插件", role: installed ? .destructive : nil) { confirmAction = true }
                            .disabled(busy || requestID != nil || !editable || !installed && (plugin["availability"].string ?? "AVAILABLE") != "AVAILABLE" || !installed && !["AVAILABLE", "INSTALLED_BY_DEFAULT"].contains(plugin["installPolicy"].text))
                        Button("返回目录") { self.detail = nil }.disabled(busy)
                    } footer: { Text("插件可能包含技能、应用、MCP 服务和运行钩子。安装和卸载会改变此工作区配置。") }
                } else {
                    Section {
                        Picker("插件搜索范围", selection: $searchMode) {
                            Text("当前目录").tag("directory"); Text("全局").tag("global"); Text("工作区").tag("workspace"); Text("个人").tag("personal")
                        }.disabled(busy)
                        TextField(searchMode == "directory" ? "查找当前目录中的插件" : "搜索插件", text: $search).autocorrectionDisabled().disabled(busy)
                            .onSubmit { if searchMode != "directory" { Task { await load() } } }
                        if searchMode != "directory" { Button("搜索插件") { Task { await load() } }.disabled(busy || search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) }
                    } footer: { Text(searchMode == "directory" ? "当前项目的原生插件目录" : resultsTerm.isEmpty ? "搜索原生插件目录" : "搜索结果 · " + resultsTerm) }
                    ForEach(filteredRows, id: \.stableID) { plugin in
                        Button { Task { await loadDetail(plugin) } } label: { HStack { VStack(alignment: .leading, spacing: 4) { Text(plugin["interface"]["displayName"].string ?? plugin["name"].text); Text(plugin["marketplaceName"].text).font(.caption).foregroundStyle(Design.secondary) }; Spacer(); Text(plugin["installed"].bool == true ? "已安装" : "查看").font(.caption).foregroundStyle(Design.secondary) } }.disabled(busy)
                    }
                    if loaded && filteredRows.isEmpty { Text(rows.isEmpty ? "没有可用插件" : "没有匹配的插件").foregroundStyle(Design.secondary) }
                }
                if detail == nil, nextCursor != nil { Button("加载更多") { Task { await load(more: true) } }.disabled(busy) }
                if let failure { Text(failure).foregroundStyle(Design.secondary) }
                if let readFailure { Text(readFailure).foregroundStyle(Design.secondary) }
                Button(searchMode == "directory" ? "刷新目录" : "刷新搜索") { Task { await load(refreshExisting: true) } }.disabled(busy)
                if requestID != nil { Button("核对原请求") { Task { await check() } }.disabled(busy) }
            }.navigationTitle("插件").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() }.disabled(busy) } }
        }.interactiveDismissDisabled(busy)
            .confirmationDialog(detail?["summary"]["installed"].bool == true ? "卸载此工作区插件？" : "安装此工作区插件？", isPresented: $confirmAction, titleVisibility: .visible) { Button(detail?["summary"]["installed"].bool == true ? "卸载" : "安装") { Task { await submit() } } }
            .onChange(of: current) { _, value in if !value { rows = []; detail = nil; dismiss() } }
            .onChange(of: searchMode) { _, value in
                rows = []; detail = nil; loaded = false; nextCursor = nil; seenCursors = []; resultsTerm = ""; readFailure = nil
                if value == "directory" { Task { await load() } }
            }
            .task { await restore(); await load() }
    }
    private func searchQuery(_ context: JSONValue) -> String {
        "search=" + ConsoleAddress.component(context["searchTerm"].text) + "&scope=" + ConsoleAddress.component(context["scope"].text) + (context["cursor"].string.map { "&cursor=" + ConsoleAddress.component($0) } ?? "")
    }
    private func load(more: Bool = false, refreshExisting: Bool = false) async {
        guard current, !busy else { return }
        var context: JSONValue?
        if searchMode != "directory" {
            let term = (more || refreshExisting) && !resultsTerm.isEmpty ? resultsTerm : search.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !term.isEmpty, !more || nextCursor != nil else { return }
            context = .object(["searchTerm": .string(term), "scope": .string(searchMode), "cursor": more ? nextCursor.map(JSONValue.string) ?? .null : .null])
        }
        busy = true; defer { busy = false }
        do {
            let page = try await model.deviceRequest(path + (context.map { "?" + searchQuery($0) } ?? "")); guard current, !Task.isCancelled else { return }
            guard page["threadId"].text == thread.id, case .array(let items) = page["plugins"], items.allSatisfy({ $0["id"].string?.isEmpty == false && $0["name"].string?.isEmpty == false && $0["installed"].bool != nil }), Set(items.map { $0["id"].text }).count == items.count else { throw APIError("插件目录格式无效") }
            if let context {
                guard items.allSatisfy({ $0["discovery"] == context }), page["nextCursor"] == .null || page["nextCursor"].string?.isEmpty == false else { throw APIError("插件搜索分页身份无效") }
                if let cursor = page["nextCursor"].string, cursor == context["cursor"].string || more && seenCursors.contains(cursor) { throw APIError("插件搜索分页游标重复") }
                if more && items.contains(where: { item in rows.contains { $0["id"] == item["id"] } }) { throw APIError("插件搜索分页身份重复，请重新搜索") }
                if !more { seenCursors = [] }
                if let cursor = context["cursor"].string { seenCursors.insert(cursor) }
                nextCursor = page["nextCursor"].string; resultsTerm = context["searchTerm"].text
            } else { nextCursor = nil; seenCursors = [] }
            rows = more ? rows + items : items; detail = nil; loaded = true; readFailure = page["errors"].array.isEmpty ? nil : page["errors"].array.map { $0["message"].text }.joined(separator: "\n")
        } catch { if current { readFailure = error.localizedDescription } }
    }
    private func loadDetail(_ plugin: JSONValue) async {
        guard current, !busy else { return }; busy = true; defer { busy = false }
        do {
            let page = try await model.deviceRequest(path + "?pluginId=" + ConsoleAddress.component(plugin["id"].text) + (plugin["discovery"] == .null ? "" : "&" + searchQuery(plugin["discovery"]))); guard current, !Task.isCancelled else { return }
            guard page["threadId"].text == thread.id, page["plugin"]["summary"]["id"] == plugin["id"], page["plugin"]["discovery"] == plugin["discovery"] else { throw APIError("插件详情身份不匹配") }
            detail = page["plugin"]; readFailure = nil
        } catch { if current { readFailure = error.localizedDescription } }
    }
    private func reconcile(_ job: JSONValue, id: String) throws {
        guard current else { return }; let receipt = try PluginReceipt(job)
        guard job["id"].text == id, try model.pending.existingRequestID(scope: scope, target: "plugin-management", path: receipt.path, body: receipt.body) == id else { throw APIError("插件管理凭证身份不匹配，原请求已保留") }
        try model.pending.reconcile(scope: scope, job: job)
        if receipt.completed {
            requestID = nil
            if job["result"]["installed"].bool == true {
                if case .array(let apps) = job["result"]["appsNeedingAuth"], apps.allSatisfy({ $0["name"].string?.isEmpty == false }) { failure = apps.isEmpty ? "已安装" : "已安装，以下应用需要授权：" + apps.map { $0["name"].text }.joined(separator: "、") }
                else { failure = "已安装，应用授权状态待核对" }
            } else { failure = "已卸载" }
        } else if ["failed", "interrupted", "acknowledged"].contains(job["state"].text) { requestID = nil; failure = job["error"].string ?? "操作未完成" }
        else { failure = job["error"].string ?? "结果待核对，原请求已保留" }
    }
    private func restore() async {
        guard current else { return }
        do { for id in try model.pending.requestIDs(scope: scope, target: "plugin-management") { requestID = id; try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id); if requestID != nil { break } } }
        catch { if current { failure = error.localizedDescription } }
    }
    private func check() async {
        guard current, !busy, let id = requestID else { return }; busy = true
        do { try reconcile(await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)), id: id) } catch { if current { failure = error.localizedDescription } }
        busy = false; if requestID == nil { await load(refreshExisting: true) }
    }
    private func submit() async {
        guard editable, !busy, requestID == nil, let detail else { return }
        let plugin = detail["summary"], installed = plugin["installed"].bool == true
        guard installed || (plugin["availability"].string ?? "AVAILABLE") == "AVAILABLE" && ["AVAILABLE", "INSTALLED_BY_DEFAULT"].contains(plugin["installPolicy"].text) else { return }
        var body: JSONValue = .object(["action": .string(installed ? "uninstall" : "install"), "pluginId": plugin["id"]])
        if detail["discovery"] != .null { body = body.setting("discovery", detail["discovery"]) }
        busy = true; failure = nil; var admitted = false
        do {
            let id = try model.pending.requestID(scope: scope, target: "plugin-management", path: path, body: body); requestID = id
            var job = try await model.deviceRequest(path, body: body.setting("requestId", .string(id))); admitted = true
            for _ in 0..<60 where ["preparing", "dispatching"].contains(job["state"].text) { guard current else { busy = false; return }; try await Task.sleep(for: .milliseconds(300)); job = try await model.deviceRequest("/api/jobs/" + ConsoleAddress.component(id)) }
            try reconcile(job, id: id)
        } catch { if current { if !admitted, (error as? APIError)?.isWriteRejection == true, let id = requestID { try? model.pending.resolve(scope: scope, target: "plugin-management", requestID: id); requestID = nil }; failure = error.localizedDescription } }
        busy = false; if requestID == nil { await load(refreshExisting: true) }
    }
}
