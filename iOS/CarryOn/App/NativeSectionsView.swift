import SwiftUI
import CarryOnCore

/// Native cursors and ordering stay separate from the local project directory.
@MainActor @Observable final class NativeSectionPage {
    var rows: [Record] = []
    var cursor: String?
    var busy = false
    var failure: String?
    private var version = UUID()
    private var cursors = Set<String>()
    func load(_ model: AppModel, path: String, key: String, more: Bool = false) async {
        guard !busy, model.allows(.view), model.status["supportsThreadSections"].bool == true, !more || cursor != nil else { return }
        let scope = model.scope, token = UUID(), next = more ? cursor : nil
        version = token; busy = true; failure = nil
        if !more { cursors = [] }
        defer { if version == token { busy = false } }
        do {
            let result = try await model.deviceRequest(path + "?limit=50" + (next.map { "&cursor=" + ConsoleAddress.component($0) } ?? ""))
            guard !Task.isCancelled, model.scope == scope, model.allows(.view), model.status["supportsThreadSections"].bool == true, version == token else { return }
            guard case .array(let values) = result[key], result.object?.keys.contains("nextCursor") == true,
                  result["nextCursor"] == .null || result["nextCursor"].string?.isEmpty == false else { throw APIError("原生分组分页回执无效") }
            let records = try values.map(Record.init)
            guard Set(records.map(\.id)).count == records.count else { throw APIError("原生分组记录重复") }
            if let next = result["nextCursor"].string, !cursors.insert(next).inserted { throw APIError("分组分页游标重复") }
            rows = more ? rows + records.filter { row in !rows.contains { $0.id == row.id } } : records
            cursor = result["nextCursor"].string
        } catch { if !Task.isCancelled, model.scope == scope, version == token { failure = error.localizedDescription } }
    }
    func reset() { version = UUID(); busy = false; rows = []; cursor = nil; cursors = []; failure = nil }
}

struct NativeSectionsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var page = NativeSectionPage()
    @State private var openingScope: String?
    @State private var editingSection: Record?
    @State private var showEditor = false
    private var allowed: Bool { model.allows(.view) && model.status["supportsThreadSections"].bool == true }
    var body: some View {
        NavigationStack {
            List {
                ForEach(page.rows) { section in
                    NavigationLink {
                        NativeSectionThreadsView(section: section, scope: model.scope) { thread in guard allowed, openingScope == model.scope else { return }; model.selectedProject = nil; model.open(thread); dismiss() }
                    } label: { Label(section.value["pinned"].bool == true ? "置顶" : section.title, systemImage: section.value["pinned"].bool == true ? "pin" : "folder") }
                    .contextMenu { if section.value["pinned"].bool != true { Button("编辑分组") { editingSection = section; showEditor = true }.disabled(!allowed || !model.canWrite(.edit)) } }
                }
                if page.busy { ProgressView() }
                if let failure = page.failure { Text(failure).foregroundStyle(.red); Button("重试") { Task { await page.load(model, path: "/api/sections", key: "sections") } } }
                if page.cursor != nil { Button("加载更多分组") { Task { await page.load(model, path: "/api/sections", key: "sections", more: true) } }.disabled(page.busy) }
            }.navigationTitle("分组").toolbar { ToolbarItem(placement: .primaryAction) { Button { editingSection = nil; showEditor = true } label: { Image(systemName: "plus") }.accessibilityLabel("新建分组").disabled(!allowed || !model.canWrite(.edit)) }; ToolbarItem(placement: .cancellationAction) { Button("完成") { dismiss() } } }
                .task(id: model.scope) {
                    if let openingScope, openingScope != model.scope { page.reset(); dismiss(); return }
                    openingScope = model.scope; page.reset(); await page.load(model, path: "/api/sections", key: "sections")
                }
                .refreshable { await page.load(model, path: "/api/sections", key: "sections") }
                .onChange(of: allowed) { _, value in if !value { page.reset() } }
        }.sheet(isPresented: $showEditor) { SectionManagementView(section: editingSection, scope: openingScope ?? model.scope) { Task { await page.load(model, path: "/api/sections", key: "sections") } } }
    }
}

private struct NativeSectionThreadsView: View {
    @Environment(AppModel.self) private var model
    let section: Record
    let scope: String
    let open: (Record) -> Void
    @State private var page = NativeSectionPage()
    @State private var orderingThread: Record?
    private var allowed: Bool { model.scope == scope && model.allows(.view) && model.status["supportsThreadSections"].bool == true }
    private var path: String { "/api/sections/" + ConsoleAddress.component(section.id) + "/threads" }
    var body: some View {
        List {
            ForEach(page.rows) { thread in Button { if allowed { open(thread) } } label: { ThreadRow(record: thread) }.buttonStyle(.plain).contextMenu { Button("调整顺序") { if allowed { orderingThread = thread } }.disabled(!allowed || !model.canWrite(.edit)) } }
            if page.busy { ProgressView() }
            if !page.busy, page.rows.isEmpty, page.failure == nil { Text("暂无会话").foregroundStyle(Design.secondary) }
            if let failure = page.failure { Text(failure).foregroundStyle(.red); Button("重试") { Task { await page.load(model, path: path, key: "threads") } } }
            if page.cursor != nil { Button("加载更多会话") { Task { await page.load(model, path: path, key: "threads", more: true) } }.disabled(page.busy) }
        }.navigationTitle(section.value["pinned"].bool == true ? "置顶" : section.title)
            .task(id: model.scope + section.id) { page.reset(); if allowed { await page.load(model, path: path, key: "threads") } }
            .refreshable { await page.load(model, path: path, key: "threads") }
            .onChange(of: allowed) { _, value in if !value { page.reset(); orderingThread = nil } }
            .sheet(item: $orderingThread) { thread in SectionManagementView(section: section, scope: scope, completed: { Task { await page.load(model, path: path, key: "threads") } }, movingThread: thread) }
    }
}

struct PinnedThreadsSummary: View {
    @Environment(AppModel.self) private var model
    @State private var rows: [Record] = []
    @State private var failure: String?
    @State private var version = UUID()
    @State private var loadedScope: String?
    private var allowed: Bool { model.allows(.view) && model.status["supportsThreadSections"].bool == true }
    let browse: () -> Void
    var body: some View {
        Group {
            if !rows.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    HStack { Text("置顶").font(.subheadline.weight(.medium)); Spacer(); Button("查看全部", action: browse).font(.caption).foregroundStyle(Design.secondary).frame(minHeight: 44) }
                    ForEach(rows.prefix(5)) { thread in Button { if allowed { model.open(thread) } } label: { ThreadRow(record: thread) }.buttonStyle(.plain) }
                }
            }
            if let failure { Button("置顶读取失败 · " + failure) { Task { await load() } }.font(.caption).foregroundStyle(Design.secondary) }
        }.task(id: model.scope + "\n" + String(model.workspaceRevision) + "\n" + String(model.connected)) {
            if loadedScope != model.scope { version = UUID(); rows = []; failure = nil; loadedScope = model.scope }
            await load()
        }.onChange(of: allowed) { _, value in
            if !value { version = UUID(); rows = []; failure = nil }
            else { Task { await load() } }
        }
    }
    private func load() async {
        guard allowed else { return }
        let scope = model.scope, token = UUID()
        version = token; failure = nil
        do {
            // Resolve the native reserved group from inventory, retaining its opaque cursors.
            var cursor: String?, seen = Set<String>(), pinned: JSONValue?
            repeat {
                let inventory = try await model.deviceRequest("/api/sections?limit=50" + (cursor.map { "&cursor=" + ConsoleAddress.component($0) } ?? ""))
                guard !Task.isCancelled, model.scope == scope, model.allows(.view), model.status["supportsThreadSections"].bool == true, version == token else { return }
                pinned = inventory["sections"].array.first { $0["pinned"].bool == true }
                cursor = inventory["nextCursor"].string
                if let cursor, !seen.insert(cursor).inserted { throw APIError("分组分页游标重复") }
                if seen.count >= 100 { throw APIError("分组列表过长，请在分组中查看") }
            } while pinned == nil && cursor != nil
            guard let section = pinned else { rows = []; return }
            let result = try await model.deviceRequest("/api/sections/" + ConsoleAddress.component(section["id"].text) + "/threads?limit=5")
            guard !Task.isCancelled, model.scope == scope, model.allows(.view), model.status["supportsThreadSections"].bool == true, version == token else { return }
            rows = try result["threads"].array.map(Record.init)
        } catch { if !Task.isCancelled, model.scope == scope, model.allows(.view), model.status["supportsThreadSections"].bool == true, version == token { failure = error.localizedDescription } }
    }
}
