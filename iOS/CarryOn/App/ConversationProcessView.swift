import SwiftUI
import CarryOnCore

struct ConversationProcessView: View {
    @Environment(\.conversationDisclosureState) private var disclosure
    @State private var localExpanded = false
    @State private var showingAll = false
    let item: JSONValue
    let threadID: String
    private var key: String { threadID + "\n" + item.stableID }
    private var running: Bool { item["active"].bool == true }
    private var expanded: Bool { disclosure?.expanded.contains(key) ?? localExpanded }
    private var entries: [JSONValue] { ConversationProcess.bodyItems(item) }
    private func setExpanded(_ value: Bool) {
        if let disclosure {
            if value { disclosure.expanded.insert(key) } else { disclosure.expanded.remove(key) }
        } else { localExpanded = value }
    }
    var body: some View {
        stage
    }
    private var stage: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { setExpanded(!expanded) } label: {
                HStack(spacing: 7) {
                    if running { ProgressView().controlSize(.mini) }
                    Text(ConversationProcess.summaryLabel(item)).lineLimit(1)
                    if item["status"].text == "interrupted" { Text("已中断") }
                    if !entries.isEmpty { Image(systemName: expanded ? "chevron.down" : "chevron.right").font(.system(size: 10)) }
                    Spacer(minLength: 0)
                }.font(.subheadline).foregroundStyle(Design.secondary)
                    .frame(minHeight: 44).contentShape(Rectangle())
            }.buttonStyle(.plain).disabled(entries.isEmpty).accessibilityValue(entries.isEmpty ? "" : expanded ? "已展开" : "已收起")
            if expanded && !entries.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(entries.prefix(5)), id: \.stableID) { entry in
                        ProcessContentRow(item: entry, threadID: threadID, anchorID: item.stableID)
                    }
                    if entries.count > 5 {
                        Button("查看完整过程（\(entries.count) 项）") { showingAll = true }.frame(minHeight: 44)
                    }
                }.padding(.top, 4)
                .sheet(isPresented: $showingAll) {
                    NavigationStack {
                        ScrollView { LazyVStack(alignment: .leading, spacing: 12) {
                            ForEach(entries, id: \.stableID) { entry in
                                ProcessContentRow(item: entry, threadID: threadID, anchorID: item.stableID)
                            }
                        }.padding(20) }
                        .navigationTitle("执行过程").navigationBarTitleDisplayMode(.inline)
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { showingAll = false } } }
                    }
                }
            }
        }
    }
}

private struct ProcessContentRow: View {
    let item: JSONValue
    let threadID: String
    let anchorID: String
    var body: some View {
        if !item["subagents"].array.isEmpty {
            AgentActivityGroup(items: [item], parentID: threadID, anchorID: anchorID)
        } else {
            TimelineEntry(item: item, threadID: threadID)
                .contextMenu {
                    if item["type"].text == "agentMessage" { Button("复制原文") { UIPasteboard.general.string = item["text"].text } }
                }
        }
    }
}
