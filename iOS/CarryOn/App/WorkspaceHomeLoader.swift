import Foundation
import CarryOnCore

/// One in-flight home refresh; a manual full sync survives ordinary live updates.
@MainActor @Observable final class WorkspaceHomeLoader {
    private var identity = ""
    private var token: UUID?
    private var pending = false
    private var pendingFullSync = false

    func load(model: AppModel, projects: RecordListState, threads: RecordListState,
              includeInactive: Bool, refresh: Bool, fullSync: Bool) async {
        let scope = model.scope, key = scope + String(includeInactive)
        if token != nil, identity == key {
            pending = true; pendingFullSync = pendingFullSync || fullSync; return
        }
        let version = UUID(); token = version; identity = key
        var refresh = refresh, fullSync = fullSync
        defer { if token == version { token = nil } }
        repeat {
            pending = false; pendingFullSync = false
            for (path, field, state) in [("/api/projects", "projects", projects), ("/api/workspace/threads", "threads", threads)] {
                guard token == version, scope == model.scope, !Task.isCancelled else { return }
                if !refresh, !state.records.isEmpty, Date().timeIntervalSince(state.updatedAt) < 30 { continue }
                let request = UUID(); state.requestVersion = request
                state.loadKind = state.records.isEmpty ? .initial : .background
                defer { if state.requestVersion == request { state.loadKind = nil } }
                do {
                    let path = path + "?limit=50&offset=0&search=&filter=all&availableOnly=\(!includeInactive)"
                    if state.records.isEmpty, let cached = try? RecordPage(model.cachedValue(path), key: field) {
                        state.records = cached.records; state.total = cached.total; state.offset = cached.nextOffset
                    }
                    var value = try await model.cachedDeviceRequest(path + (fullSync ? "&refreshStatuses=true&sync=full" : ""), maxAge: refresh ? 0 : 30)
                    if fullSync, value["sync"]["state"].string == nil { throw APIError("未收到完整同步状态，请更新桌面端 CarryOn") }
                    while value["sync"]["state"].string == "running" {
                        guard token == version, scope == model.scope, !Task.isCancelled else { return }
                        guard let syncID = value["sync"]["id"].string else { throw APIError("同步响应缺少标识") }
                        try await Task.sleep(for: .milliseconds(500))
                        value = try await model.cachedDeviceRequest(path + "&syncId=" + ConsoleAddress.component(syncID), maxAge: 0)
                    }
                    if fullSync, value["sync"]["state"].string != "completed" { throw APIError(value["sync"]["error"].string ?? "同步未完成，请重试") }
                    let page = try RecordPage(value, key: field)
                    guard token == version, scope == model.scope, !Task.isCancelled, state.requestVersion == request else { return }
                    state.records = page.records; state.total = page.total; state.offset = page.nextOffset
                    state.updatedAt = Date(); state.failure = nil
                } catch {
                    if token == version, scope == model.scope, !Task.isCancelled, state.requestVersion == request {
                        state.failure = error.localizedDescription
                    }
                }
            }
            guard token == version, scope == model.scope, !Task.isCancelled else { return }
            refresh = true; fullSync = pendingFullSync
        } while pending
    }
}
