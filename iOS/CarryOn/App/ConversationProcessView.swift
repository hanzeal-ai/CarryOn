import SwiftUI
import CarryOnCore

struct ConversationProcessView: View {
    @Environment(\.conversationDisclosureState) private var disclosure
    @State private var localExpanded = false
    let item: JSONValue
    let threadID: String
    private var key: String { threadID + "\n" + item.stableID }
    private var running: Bool { item["active"].bool == true }
    private var expanded: Bool { disclosure?.expanded.contains(key) ?? localExpanded }
    private var entries: [JSONValue] { ConversationProcess.bodyItems(item) }
    private var toolCount: Int {
        entries.filter { ["commandExecution", "fileChange", "webSearch", "mcpToolCall", "dynamicToolCall", "functionCallOutput"].contains($0["type"].text) }.count
    }
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
                    Text(!running && toolCount > 0 ? AttributedString("调用了 \(toolCount) 个工具") : ConversationProcess.summaryLabel(item)).lineLimit(1)
                    if item["status"].text == "interrupted" { Text("已中断") }
                    if !entries.isEmpty { Image(systemName: expanded ? "chevron.down" : "chevron.right").font(.system(size: 10)) }
                    Spacer(minLength: 0)
                }.font(.subheadline).foregroundStyle(Design.secondary)
                    .frame(minHeight: 32).contentShape(Rectangle())
            }.buttonStyle(.plain).disabled(entries.isEmpty).accessibilityValue(entries.isEmpty ? "" : expanded ? "已展开" : "已收起")
            if expanded && !entries.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(entries, id: \.stableID) { entry in
                        ProcessContentRow(item: entry, threadID: threadID, anchorID: item.stableID)
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
