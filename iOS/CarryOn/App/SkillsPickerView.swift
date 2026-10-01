import SwiftUI
import CarryOnCore

struct SkillsPickerView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ConversationActionTarget
    @State private var catalog: [JSONValue] = []
    @State private var errors: [JSONValue] = []
    @State private var loading = true
    @State private var failure: String?
    @State private var query = ""
    private var current: Bool { model.scope == target.scope && model.selectedThread?.id == target.threadID }
    private var rows: [JSONValue] {
        catalog.filter { query.isEmpty || ($0["name"].text + " " + $0["description"].text).localizedCaseInsensitiveContains(query) }
    }
    var body: some View {
        NavigationStack {
            List {
                if loading { ProgressView("正在读取技能…") }
                if let failure { Text(failure).foregroundStyle(.red); Button("重试") { Task { await load() } } }
                ForEach(errors, id: \.stableID) { error in
                    Text(error["message"].string ?? error["path"].text).font(.caption).foregroundStyle(.red)
                }
                if !loading && failure == nil && rows.isEmpty { Text(query.isEmpty ? "当前项目没有可用技能" : "没有匹配的技能").foregroundStyle(Design.secondary) }
                ForEach(rows, id: \.stableID) { skill in
                    let reference = SkillReference(name: skill["name"].text, path: skill["path"].text)
                    let selected = model.draftSkills.contains(reference)
                    Button {
                        guard current, model.history["controls"]["supportsSkills"].bool == true else { return }
                        if selected { model.draftSkills.removeAll { $0 == reference } }
                        else if model.draftSkills.count < 20 { model.draftSkills.append(reference) }
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "square.stack.3d.up").foregroundStyle(Design.secondary)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(skill["interface"]["displayName"].string ?? reference.name).foregroundStyle(Design.ink)
                                Text(skill["interface"]["shortDescription"].string ?? skill["description"].text).font(.caption).foregroundStyle(Design.secondary).lineLimit(3)
                            }
                            Spacer(minLength: 8)
                            if selected { Image(systemName: "checkmark").foregroundStyle(Design.link) }
                        }.padding(.vertical, 4)
                    }.disabled(!current || skill["enabled"].bool != true || (!selected && model.draftSkills.count >= 20))
                        .accessibilityLabel(reference.name).accessibilityAddTraits(selected ? .isSelected : [])
                }
            }.navigationTitle("技能").navigationBarTitleDisplayMode(.inline)
                .searchable(text: $query, prompt: "搜索技能")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
                .task { await load() }
                .onChange(of: current) { _, value in if !value { dismiss() } }
        }
    }
    private func load() async {
        guard current else { return }
        loading = true; failure = nil
        do {
            let result = try await model.deviceRequest("/api/threads/" + ConsoleAddress.component(target.threadID) + "/skills")
            guard !Task.isCancelled, current else { return }
            catalog = result["skills"].array; errors = result["errors"].array
        } catch { if current { failure = error.localizedDescription } }
        if current { loading = false }
    }
}

struct DraftSkillChips: View {
    @Binding var skills: [SkillReference]
    var disabled = false
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(skills, id: \.self) { skill in
                    Button { skills.removeAll { $0 == skill } } label: {
                        HStack(spacing: 6) { Image(systemName: "square.stack.3d.up"); Text(skill.name); Image(systemName: "xmark").font(.caption2) }
                            .font(.subheadline).padding(.horizontal, 12).padding(.vertical, 8)
                            .foregroundStyle(Design.link).background(Design.link.opacity(0.08), in: Capsule())
                    }.buttonStyle(.plain).disabled(disabled).accessibilityLabel("移除技能 " + skill.name)
                }
            }
        }
    }
}

struct MessageSkillReferences: View {
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
                    .accessibilityLabel("技能：" + skill["name"].text)
            }
        }
    }
}
