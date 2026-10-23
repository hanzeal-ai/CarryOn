import SwiftUI
import ExyteChat
import CarryOnCore

/// Lives above reusable table cells so snapshot updates do not reset open details.
@MainActor @Observable final class ConversationDisclosureState {
    var expanded: Set<String> = []
}

@MainActor final class ConversationReadingState {
    let disclosure = ConversationDisclosureState()
    var visiblePosition: (id: String, offset: CGFloat)?
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

extension ChatView {
    func carryOnChatAppearance() -> some View {
        localization(.init(inputPlaceholder: "继续对话…", signatureText: "添加说明", cancelButtonText: "取消",
                           recentToggleText: "最近", waitingForNetwork: "等待连接", recordingText: "录音", replyToText: "回复"))
            .chatTheme(colors: .init(mainBG: Design.canvas, mainTint: Design.ink, inputBG: Design.input,
                                    inputText: Design.ink, sendButtonBackground: Design.composerAccent))
    }
}

/// The outgoing bubble retains submitted text until native history is visible.
struct OutgoingMessageStatusView: View {
    @Environment(AppModel.self) private var model
    @State private var checking = false
    let item: JSONValue
    let dismiss: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !item["prompt"].text.isEmpty || (item["skills"].array + item["mentions"].array + item["files"].array).isEmpty {
                Text(item["prompt"].text.isEmpty ? "图片消息" : OutgoingMessageProjection.displayText(item["prompt"].text)).textSelection(.enabled)
            }
            MessageComposerReferences(skills: item["skills"].array + item["mentions"].array)
            ForEach(item["files"].array, id: \.stableID) { file in Label(file["name"].text, systemImage: "doc").font(.subheadline) }
            if !["sending", "preparing", "dispatching"].contains(item["state"].text) {
                let labels = ["failed": "发送失败，请核对请求记录", "uncertain": "结果待核对，请勿重复发送"]
                Text(labels[item["state"].text] ?? (item["kind"].text == "operation:queue-add" ? "已排队，等待同步" : "已接收，等待同步")).font(.caption).foregroundStyle(Design.secondary)
            }
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
    var skills: Binding<[ComposerReference]>? = nil
    var selection: Binding<Int>? = nil
    var disabled = false
    var draftEditable = true
    var sendAllowed = true
    var sendingReady = true
    var commandInputAllowed = false
    var stopAllowed = true
    var hasImages = false
    var stopping = false
    var submitting = false
    var resuming = false
    var sendLabel: String? = nil
    var placeholder = "跟进"
    var autofocus = false
    var compactLeading: AnyView? = nil
    var voice: (() -> Void)? = nil
    var draftHeader: AnyView? = nil
    @State private var editing = false
    @FocusState private var textFocused: Bool
    private var expanded: Bool { compactLeading == nil || editing || textFocused || !text.isEmpty || hasImages || !(skills?.wrappedValue.isEmpty ?? true) }
    let send: () -> Void
    var stop: (() -> Void)?
    var resume: (() -> Void)?
    @ViewBuilder var accessories: Accessories
    private var action: ComposerAction { submitting ? .pause : .resolve(text: sendAllowed ? text : "", hasImages: sendAllowed && hasImages, running: stopping, interrupted: resuming) }
    private var actionDisabled: Bool { disabled || submitting || action == .unavailable || (action == .pause ? !stopAllowed : (!sendAllowed || !sendingReady)) }
    private var buttonLabel: String { submitting ? "正在提交，请稍候" : action == .pause ? "停止执行" : action == .restart ? "继续执行" : sendLabel ?? (stopping ? "补充到当前任务" : "发送") }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let draftHeader { draftHeader.padding(.horizontal, 2).padding(.top, 6) }
            HStack(alignment: .center, spacing: 0) {
                if !expanded, let compactLeading { compactLeading }
                editor
                    .padding(.horizontal, expanded ? 12 : 2)
                    .padding(.top, expanded ? 13 : 0)
                    .padding(.bottom, expanded ? 12 : 0)
                if !expanded {
                    if action == .unavailable, let voice {
                        Button(action: voice) {
                            Image(systemName: "waveform").font(.system(size: 17, weight: .medium))
                                .foregroundStyle(Design.onAccent).frame(width: 32, height: 32)
                                .background(Design.ink, in: Circle()).frame(width: 44, height: 44)
                        }.disabled(disabled).accessibilityLabel("语音聊天")
                    } else { actionButton }
                }
            }
            if expanded {
                HStack(alignment: .center, spacing: 0) {
                    accessories.foregroundStyle(theme.colors.mainTint)
                    if action == .send, stopping, let stop {
                        Button(action: stop) {
                            Image(systemName: "stop.fill").font(.system(size: 17, weight: .semibold))
                                .frame(width: 44, height: 44)
                        }.disabled(disabled || !stopAllowed).accessibilityLabel("停止执行")
                    }
                    actionButton
                }
            }
        }
        .foregroundStyle(theme.colors.mainTint)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: expanded)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: action)
        .padding(.horizontal, expanded ? 6 : 4).padding(.vertical, 2)
        .background(theme.colors.inputBG, in: RoundedRectangle(cornerRadius: expanded ? 26 : 30))
        .padding(.horizontal, expanded ? 12 : 32).padding(.vertical, 8)
        .background(theme.colors.mainBG)
    }
    private var editor: some View {
        Group {
            if let skills {
                ZStack(alignment: .topLeading) {
                    if text.isEmpty && skills.wrappedValue.isEmpty {
                        Text(placeholder).foregroundStyle(.secondary).allowsHitTesting(false)
                    }
                    InlineSkillEditor(text: $text, skills: skills, selection: selection ?? .constant(0),
                                      editable: draftEditable && (sendAllowed || commandInputAllowed),
                                      placeholder: placeholder, autofocus: autofocus, onEditingChanged: { editing = $0 })
                }
            } else {
                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...6).fixedSize(horizontal: false, vertical: true)
                    .focused($textFocused).onAppear { if autofocus { textFocused = true } }.disabled(!draftEditable || !(sendAllowed || commandInputAllowed))
            }
        }.font(Font(ComposerTypography.font)).lineSpacing(ComposerTypography.lineSpacing)
            .foregroundStyle(theme.colors.inputText).tint(Design.ink)
    }
    private var actionButton: some View {
        Button(action: action == .pause ? { stop?() } : action == .restart ? { resume?() } : send) {
            ZStack {
                if submitting { ComposerLoadingRing().accessibilityHidden(true) }
                else {
                    Image(systemName: action == .pause ? "stop.fill" : action == .restart ? "play.fill" : "arrow.up")
                        .font(.system(size: 17, weight: .semibold)).foregroundStyle(Design.onAccent)
                }
            }.frame(width: 32, height: 32)
                .background(actionDisabled && !submitting ? Design.secondary.opacity(0.25) : theme.colors.sendButtonBackground, in: Circle())
                .frame(width: 44, height: 44)
        }.disabled(actionDisabled).accessibilityLabel(buttonLabel)
    }
}

private struct ComposerLoadingRing: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var rotating = false

    var body: some View {
        ZStack {
            Circle().stroke(Design.onAccent.opacity(0.18), lineWidth: 1.75)
            Circle().trim(from: 0, to: 0.72)
                .stroke(Design.onAccent, style: StrokeStyle(lineWidth: 1.75, lineCap: .round))
                .rotationEffect(.degrees(reduceMotion ? -90 : rotating ? 270 : -90))
                .animation(reduceMotion ? nil : .linear(duration: 1).repeatForever(autoreverses: false), value: rotating)
        }.frame(width: 24, height: 24)
            .onAppear { rotating = true }
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

// The Side-chat ChatView still consumes its library menu protocol.
extension CarryOnMessageAction: MessageMenuAction {
    static func menuItems(for message: ExyteChat.Message) -> [Self] {
        guard let item = message.customData["entry"] as? JSONValue else { return [] }
        return menuItems(forType: item["type"].text, canEdit: message.customData["canEdit"] as? Bool == true)
    }
}
