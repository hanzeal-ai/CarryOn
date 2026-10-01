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
            if !item["prompt"].text.isEmpty || item["skills"].array.isEmpty {
                Text(item["prompt"].text.isEmpty ? "图片消息" : OutgoingMessageProjection.displayText(item["prompt"].text)).textSelection(.enabled)
            }
            MessageSkillReferences(skills: item["skills"].array)
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
    var disabled = false
    var draftEditable = true
    var sendAllowed = true
    var stopAllowed = true
    var hasImages = false
    var stopping = false
    var submitting = false
    var resuming = false
    var sendLabel: String? = nil
    var placeholder = "继续对话…"
    let send: () -> Void
    var stop: (() -> Void)?
    var resume: (() -> Void)?
    @ViewBuilder var accessories: Accessories
    private var action: ComposerAction { submitting ? .pause : .resolve(text: sendAllowed ? text : "", hasImages: sendAllowed && hasImages, running: stopping, interrupted: resuming) }
    private var actionDisabled: Bool { disabled || submitting || action == .unavailable || (action == .pause ? !stopAllowed : !sendAllowed) }
    private var buttonLabel: String { submitting ? "正在提交，请稍候" : action == .pause ? "停止执行" : action == .restart ? "继续执行" : sendLabel ?? (stopping ? "补充到当前任务" : "发送") }
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            TextField(stopping ? "补充要求…" : placeholder, text: $text, axis: .vertical)
                .font(.body).lineLimit(1...6).fixedSize(horizontal: false, vertical: true).disabled(!draftEditable || !sendAllowed)
                .foregroundStyle(theme.colors.inputText).tint(Design.composerAccent)
                .padding(.horizontal, 12).padding(.top, 10)
            HStack(alignment: .center, spacing: 0) {
                accessories.foregroundStyle(theme.colors.mainTint)
                if action == .send, stopping, let stop {
                    Button(action: stop) {
                        Image(systemName: "stop.fill")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(theme.colors.mainTint).frame(width: 44, height: 44)
                    }.disabled(disabled || !stopAllowed).accessibilityLabel("停止执行")
                }
                Button(action: action == .pause ? { stop?() } : action == .restart ? { resume?() } : send) {
                    ZStack {
                        if submitting {
                            ComposerLoadingRing()
                                .accessibilityHidden(true)
                        }
                        if !submitting { Image(systemName: action == .pause ? "stop.fill" : action == .restart ? "play.fill" : "arrow.up")
                            .font(.system(size: submitting ? 9 : 17, weight: .semibold))
                            .foregroundStyle(.white) }
                    }.frame(width: 32, height: 32).background(actionDisabled && !submitting ? Design.secondary.opacity(0.25) : theme.colors.sendButtonBackground, in: Circle())
                        .frame(width: 44, height: 44)
                }.disabled(actionDisabled)
                    .accessibilityLabel(buttonLabel)
            }
        }.animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: action)
            .padding(.horizontal, 6).padding(.vertical, 4)
            .background(theme.colors.inputBG, in: RoundedRectangle(cornerRadius: 28))
            .overlay(RoundedRectangle(cornerRadius: 28).stroke(Design.surface.opacity(0.85), lineWidth: 1))
            .shadow(color: .black.opacity(0.08), radius: 18, x: 0, y: 5)
            .padding(.horizontal, 12).padding(.vertical, 8).background(theme.colors.mainBG)
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
