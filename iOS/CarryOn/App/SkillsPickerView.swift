import SwiftUI
import CarryOnCore

enum ReferencePickerTarget {
    case conversation(ConversationActionTarget)
    case creation(scope: String, project: String?)
    var scope: String { switch self { case .conversation(let target): target.scope; case .creation(let scope, _): scope } }
    var draftKey: String { scope + "\n" + threadID }
    var threadID: String { switch self { case .conversation(let target): target.threadID; case .creation: "new" } }
    var path: String { switch self {
        case .conversation(let target): "/api/threads/" + ConsoleAddress.component(target.threadID)
        case .creation(_, let project): "/api/creation/references" + (project.map { "?projectId=" + ConsoleAddress.component($0) } ?? "")
    } }
    var isCreation: Bool { if case .creation = self { true } else { false } }
}

struct SkillsPickerView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ReferencePickerTarget
    var mentions = false
    private var title: String { mentions ? "应用与插件" : "技能" }
    private var capability: String { mentions ? "supportsMentions" : "supportsSkills" }
    @State private var catalog: [JSONValue] = []
    @State private var errors: [JSONValue] = []
    @State private var loading = true
    @State private var failure: String?
    @State private var query = ""
    private var current: Bool { model.scope == target.scope && (target.isCreation || model.selectedThread?.id == target.threadID) }
    private var supported: Bool { target.isCreation ? model.status["supportsCreationReferences"].bool == true : model.history["controls"][capability].bool == true }
    private var references: [ComposerReference] { model.draftStore.skills[target.draftKey] ?? [] }
    private var rows: [JSONValue] {
        catalog.filter { query.isEmpty || ($0["name"].text + " " + $0["interface"]["displayName"].text + " " + $0["description"].text).localizedCaseInsensitiveContains(query) }
    }
    var body: some View {
        NavigationStack {
            List {
                if loading { ProgressView("正在读取" + title + "…") }
                if let failure { Text(failure).foregroundStyle(.red); Button("重试") { Task { await load() } } }
                ForEach(errors, id: \.stableID) { error in
                    Text(error["message"].string ?? error["path"].text).font(.caption).foregroundStyle(.red)
                }
                if !loading && failure == nil && rows.isEmpty { Text(query.isEmpty ? "当前项目没有可用" + title : "没有匹配的" + title).foregroundStyle(Design.secondary) }
                ForEach(rows, id: \.stableID) { skill in
                    let reference = ComposerReference(name: skill["name"].text, path: skill["path"].text, displayName: skill["interface"]["displayName"].string, iconData: skill["iconData"].string)
                    let selected = references.contains { $0.name == reference.name && $0.path == reference.path }
                    Button {
                        guard current, supported else { return }
                        var document = ComposerDocument(text: model.draftStore.texts[target.draftKey] ?? "", skills: references)
                        let caret = model.composerSelections[target.draftKey] ?? (document.text as NSString).length
                        if selected { document.remove(reference) }
                        else if document.skills.count < 20 { document.insert(reference, at: caret); model.composerSelections[target.draftKey] = caret + 1 }
                        model.draftStore.texts[target.draftKey] = document.text; model.draftStore.skills[target.draftKey] = document.skills; model.draftStore.save()
                    } label: {
                        HStack(spacing: 12) {
                            Group {
                                if let image = ReferenceIcon.image(reference.iconData) { Image(uiImage: image).resizable().scaledToFit() }
                                else { Image(systemName: reference.isMention ? "square.grid.2x2" : "cube").foregroundStyle(Design.secondary) }
                            }.frame(width: 24, height: 24)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(skill["interface"]["displayName"].string ?? reference.name).foregroundStyle(Design.ink)
                                Text(skill["interface"]["shortDescription"].string ?? skill["description"].text).font(.caption).foregroundStyle(Design.secondary).lineLimit(3)
                            }
                            Spacer(minLength: 8)
                            if selected { Image(systemName: "checkmark").foregroundStyle(Design.link) }
                        }.padding(.vertical, 4)
                    }.disabled(!current || !supported || skill["enabled"].bool != true || (!selected && references.count >= 20))
                        .accessibilityLabel(reference.name).accessibilityAddTraits(selected ? .isSelected : [])
                }
            }.navigationTitle(title).navigationBarTitleDisplayMode(.inline)
                .searchable(text: $query, prompt: "搜索" + title)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .task { await load() }
                .onChange(of: current) { _, value in if !value { dismiss() } }
        }
    }
    private func load() async {
        guard current else { return }
        loading = true; failure = nil
        do {
            let result = try await model.deviceRequest(target.path + (target.isCreation ? "" : mentions ? "/mentions" : "/skills"))
            guard !Task.isCancelled, current else { return }
            catalog = result[mentions ? "mentions" : "skills"].array; errors = result["errors"].array
        } catch { if current { failure = error.localizedDescription } }
        if current { loading = false }
    }
}

struct MessageComposerReferences: View {
    let skills: [JSONValue]
    var body: some View {
        if !skills.isEmpty {
            ViewThatFits(in: .horizontal) {
                labels
                ScrollView(.horizontal, showsIndicators: false) { labels }
            }.frame(maxWidth: .infinity, alignment: .trailing)
        }
    }
    private var labels: some View {
        HStack(spacing: 6) {
            ForEach(Array(skills.enumerated()), id: \.offset) { _, skill in
                Label(skill["name"].text, systemImage: "bolt.fill")
                    .font(.subheadline).foregroundStyle(.blue).padding(.horizontal, 9).padding(.vertical, 5)
                    .background(.blue.opacity(0.08), in: Capsule())
                    .accessibilityLabel(skill["name"].text)
            }
        }
    }
}
