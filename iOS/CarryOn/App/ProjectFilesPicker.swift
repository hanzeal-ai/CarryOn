import SwiftUI
import CarryOnCore

struct ProjectFilesPicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let threadID: String
    let scope: String
    @State private var search = ""
    @State private var results: [JSONValue] = []
    @State private var loaded = false
    @State private var busy = false
    @State private var failure: String?
    private var key: String { scope + "\n" + threadID }
    private var current: Bool {
        model.scope == scope && model.selectedThread?.id == threadID && model.canCompose &&
        model.allows(.files) && !model.conversationReadOnly && !model.writing &&
        model.history["controls"]["supportsFileReferences"].bool == true
    }
    private var selected: [ProjectFileReference] { model.draftStore.files[key] ?? [] }
    var body: some View {
        NavigationStack {
            List {
                HStack {
                    SearchField(text: $search, placeholder: "搜索项目文件").onSubmit { Task { await load() } }
                    Button { Task { await load() } } label: { Text("搜索").frame(minWidth: 44, minHeight: 44) }.disabled(busy || search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !current)
                }.listRowSeparator(.hidden)
                if busy { ProgressView("搜索项目文件…") }
                if let failure { Text(failure).foregroundStyle(.red) }
                if loaded && results.isEmpty && failure == nil { Text("没有匹配的项目文件").foregroundStyle(Design.secondary) }
                ForEach(results, id: \.stableID) { file in
                    let chosen = selected.contains { $0.path == file["path"].text }
                    Button {
                        toggle(file)
                    } label: {
                        HStack {
                            Image(systemName: "doc").foregroundStyle(Design.secondary)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(file["name"].text).foregroundStyle(Design.ink)
                                Text(file["relativePath"].text).font(.caption).foregroundStyle(Design.secondary)
                            }
                            Spacer()
                            if chosen { Image(systemName: "checkmark").foregroundStyle(Design.ink) }
                        }.frame(minHeight: 44)
                    }.disabled(!current || busy || (!chosen && selected.count >= 20)).accessibilityAddTraits(chosen ? [.isSelected] : [])
                }
            }.listStyle(.plain).navigationTitle("项目文件").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .onChange(of: current) { _, value in if !value { results = []; dismiss() } }
        }
    }
    private func toggle(_ file: JSONValue) {
        guard current, !busy else { return }
        if selected.contains(where: { $0.path == file["path"].text }) {
            model.draftStore.files[key]?.removeAll { $0.path == file["path"].text }
        } else if selected.count < 20 {
            model.draftStore.files[key, default: []].append(.init(name: file["name"].text, path: file["path"].text, query: file["query"].text))
        }
        model.draftStore.save()
    }
    private func load() async {
        let term = search.trimmingCharacters(in: .whitespacesAndNewlines), epoch = model.epoch
        guard current, !busy, !term.isEmpty else { return }
        guard term.count <= 200 else { failure = "搜索内容不能超过 200 个字符"; return }
        busy = true; failure = nil; results = []; loaded = false
        defer { busy = false }
        do {
            let result = try await model.deviceRequest("/api/threads/" + ConsoleAddress.component(threadID) + "/files/search?query=" + ConsoleAddress.component(term))
            guard current, model.epoch == epoch else { return }
            guard result["threadId"].text == threadID, case .array(let files) = result["files"],
                  files.allSatisfy({ !$0["name"].text.isEmpty && $0["path"].text.hasPrefix("/") && $0["query"].text == term }),
                  Set(files.map { $0["path"].text }).count == files.count else { throw APIError("项目文件搜索回执身份不匹配") }
            results = files; loaded = true
        } catch {
            if current, model.epoch == epoch { failure = error.localizedDescription }
        }
    }
}
