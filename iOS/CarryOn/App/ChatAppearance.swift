import SwiftUI
import ExyteChat
import CarryOnCore

/// Lives above reusable table cells so snapshot updates do not reset open details.
@MainActor @Observable final class ConversationDisclosureState {
    var expanded: Set<String> = []
}

@MainActor final class ConversationReadingState {
    let disclosure = ConversationDisclosureState()
    var offset: CGFloat = 0
    var anchorID: String?
    var visibleCount = 120
    var historyLimit = 40
}

private struct ConversationDisclosureStateKey: EnvironmentKey {
    static let defaultValue: ConversationDisclosureState? = nil
}
extension EnvironmentValues {
    var conversationDisclosureState: ConversationDisclosureState? {
        get { self[ConversationDisclosureStateKey.self] }
        set { self[ConversationDisclosureStateKey.self] = newValue }
    }
}

struct ConversationDisclosureGroup<Content: View, Label: View>: View {
    @Environment(\.conversationDisclosureState) private var state
    @State private var localExpanded = false
    let key: String
    @ViewBuilder var content: Content
    @ViewBuilder var label: Label
    var body: some View {
        DisclosureGroup(isExpanded: Binding(get: {
            state?.expanded.contains(key) ?? localExpanded
        }, set: { value in
            if let state {
                if value { state.expanded.insert(key) } else { state.expanded.remove(key) }
            } else { localExpanded = value }
        })) { content } label: { label }
    }
}

extension ChatView {
    func carryOnChatAppearance() -> some View {
        localization(.init(inputPlaceholder: "继续对话…", signatureText: "添加说明", cancelButtonText: "取消",
                           recentToggleText: "最近", waitingForNetwork: "等待连接", recordingText: "录音", replyToText: "回复"))
            .chatTheme(colors: .init(mainBG: Design.canvas, mainTint: Design.ink, inputBG: Design.input,
                                    inputText: Design.ink, sendButtonBackground: Design.ink))
    }
}

/// Exyte's input slot uses the app-owned draft; only a confirmed server response clears it.
struct OutgoingMessageStatusView: View {
    @Environment(AppModel.self) private var model
    @State private var checking = false
    let item: JSONValue
    let dismiss: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(item["prompt"].text.isEmpty ? "图片消息" : OutgoingMessageProjection.displayText(item["prompt"].text)).textSelection(.enabled)
            let labels = ["sending": "发送中…", "preparing": "发送中…", "dispatching": "发送中…", "failed": "发送失败，请核对请求记录", "uncertain": "结果待核对，请勿重复发送"]
            Text(labels[item["state"].text] ?? (item["kind"].text == "operation:queue-add" ? "已排队，等待同步" : "已接收，等待同步")).font(.caption).foregroundStyle(Design.secondary)
            if ["uncertain", "failed"].contains(item["state"].text) {
                HStack {
                    Button(checking ? "核对中…" : "核对结果") {
                        Task { checking = true; defer { checking = false }; await model.checkOutgoing(item) }
                    }.disabled(checking || !model.connected)
                    if item["state"].text == "failed" { Button("清除提示", action: dismiss) }
                }.font(.caption)
            }
        }.padding(13).frame(maxWidth: .infinity, alignment: .leading).background(Design.background, in: RoundedRectangle(cornerRadius: 12))
    }
}

struct CarryOnChatComposer<Accessories: View>: View {
    @Environment(\.chatTheme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Binding var text: String
    @ScaledMetric(relativeTo: .body) private var lineHeight = 22
    var disabled = false
    var draftEditable = true
    var sendAllowed = true
    var stopAllowed = true
    var hasImages = false
    var stopping = false
    var resuming = false
    let send: () -> Void
    var queue: (() -> Void)?
    var stop: (() -> Void)?
    var resume: (() -> Void)?
    @ViewBuilder var accessories: Accessories
    private var action: ComposerAction { .resolve(text: sendAllowed ? text : "", hasImages: sendAllowed && hasImages, running: stopping, interrupted: resuming) }
    private var actionDisabled: Bool { disabled || action == .unavailable || (action == .pause ? !stopAllowed : !sendAllowed) }
    private var buttonLabel: String { action == .pause ? "停止执行" : action == .restart ? "继续执行" : stopping ? "立即补充" : "发送" }
    var body: some View {
        ComposerLayout(lineHeight: lineHeight) {
            HStack(spacing: 0) { accessories }
                .foregroundStyle(theme.colors.mainTint)
            TextField(stopping ? "补充要求…" : "继续对话…", text: $text, axis: .vertical)
                .font(.body).lineLimit(1...6).disabled(!draftEditable || !sendAllowed)
                .foregroundStyle(theme.colors.inputText)
            HStack(alignment: .center, spacing: 0) {
                if action == .send, stopping, let queue {
                    Menu {
                        Button("当前执行结束后发送", systemImage: "text.badge.plus", action: queue).disabled(!sendAllowed)
                        if let stop { Button("停止当前执行", systemImage: "stop", action: stop).disabled(!stopAllowed) }
                    } label: { Label("发送方式", systemImage: "chevron.down").font(.caption).frame(minHeight: 44) }.disabled(disabled).accessibilityLabel("发送方式")
                }
                Button(action: action == .pause ? { stop?() } : action == .restart ? { resume?() } : send) {
                    Image(systemName: action == .pause ? "stop.fill" : action == .restart ? "play.fill" : "arrow.up")
                        .font(.system(size: 17, weight: .semibold)).foregroundStyle(Design.onAccent)
                        .frame(width: 36, height: 36).background(theme.colors.sendButtonBackground, in: Circle())
                        .frame(width: 44, height: 44)
                }.disabled(actionDisabled)
                    .opacity(actionDisabled ? 0.35 : 1)
                    .accessibilityLabel(buttonLabel)
            }
        }.animation(reduceMotion ? nil : .easeInOut(duration: 0.22), value: text)
            .animation(reduceMotion ? nil : .easeInOut(duration: 0.22), value: action)
            .padding(.horizontal, 6).padding(.vertical, 4)
            .background(theme.colors.inputBG, in: RoundedRectangle(cornerRadius: 24))
            .padding(.horizontal, 12).padding(.vertical, 8).background(theme.colors.mainBG)
    }
}

/// Measures the editor at its compact width, while keeping the same TextField
/// mounted during reflow so keyboard focus and selection remain intact.
private struct ComposerLayout: Layout {
    let lineHeight: CGFloat
    private func metrics(_ proposal: ProposedViewSize, _ views: Subviews) -> (CGFloat, CGSize, CGSize, CGSize, Bool) {
        let width = proposal.width ?? 320
        let accessories = views[0].sizeThatFits(.unspecified)
        let actions = views[2].sizeThatFits(.unspecified)
        let compactWidth = max(1, width - accessories.width - actions.width - 8)
        let compact = views[1].sizeThatFits(.init(width: compactWidth, height: nil))
        let expanded = compact.height > lineHeight * 1.5
        let editor = expanded ? views[1].sizeThatFits(.init(width: max(1, width - 20), height: nil)) : compact
        return (width, accessories, actions, editor, expanded)
    }
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let (width, accessories, actions, editor, expanded) = metrics(proposal, subviews)
        let controls = max(accessories.height, actions.height)
        return CGSize(width: width, height: expanded ? editor.height + controls + 14 : max(controls, editor.height))
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let (_, accessories, actions, editor, expanded) = metrics(.init(width: bounds.width, height: nil), subviews)
        let controls = max(accessories.height, actions.height)
        let centerY = expanded ? bounds.maxY - controls / 2 : bounds.midY
        subviews[0].place(at: CGPoint(x: bounds.minX, y: centerY), anchor: .leading, proposal: .init(accessories))
        subviews[2].place(at: CGPoint(x: bounds.maxX, y: centerY), anchor: .trailing, proposal: .init(actions))
        subviews[1].place(at: CGPoint(x: bounds.minX + (expanded ? 10 : accessories.width + 4),
                                     y: expanded ? bounds.minY + 10 : bounds.midY - editor.height / 2),
                          anchor: .topLeading, proposal: .init(width: expanded ? max(1, bounds.width - 20) : max(1, bounds.width - accessories.width - actions.width - 8), height: editor.height))
    }
}

private struct ConversationContentContextKey: EnvironmentKey {
    static let defaultValue = ConversationContentContext()
}
extension EnvironmentValues {
    var conversationContentContext: ConversationContentContext {
        get { self[ConversationContentContextKey.self] }
        set { self[ConversationContentContextKey.self] = newValue }
    }
}
