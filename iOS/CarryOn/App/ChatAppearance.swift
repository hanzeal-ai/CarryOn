import SwiftUI
import ExyteChat
import CarryOnCore

extension ChatView {
    func carryOnChatAppearance() -> some View {
        localization(.init(inputPlaceholder: "继续对话…", signatureText: "添加说明", cancelButtonText: "取消",
                           recentToggleText: "最近", waitingForNetwork: "等待连接", recordingText: "录音", replyToText: "回复"))
            .chatTheme(colors: .init(mainBG: .white, mainTint: Design.ink, inputBG: Design.background,
                                    inputText: Design.ink, sendButtonBackground: Design.ink))
    }
}

/// Exyte's input slot uses the app-owned draft; only a confirmed server response clears it.
struct CarryOnChatComposer<Accessories: View>: View {
    @Environment(\.chatTheme) private var theme
    @Binding var text: String
    var disabled = false
    var hasImages = false
    var stopping = false
    var resuming = false
    let send: () -> Void
    var stop: (() -> Void)?
    var resume: (() -> Void)?
    @ViewBuilder var accessories: Accessories
    private var action: ComposerAction { .resolve(text: text, hasImages: hasImages, running: stopping, interrupted: resuming) }
    private var buttonLabel: String { action == .pause ? "暂停任务" : action == .restart ? "启动任务" : "发送" }
    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            HStack(alignment: .bottom, spacing: 0) {
                accessories.foregroundStyle(theme.colors.mainTint)
                TextField("继续对话…", text: $text, axis: .vertical)
                    .font(.system(size: 16)).lineLimit(1...6)
                    .padding(.vertical, 12).padding(.horizontal, 10)
                    .foregroundStyle(theme.colors.inputText)
            }.background(theme.colors.inputBG, in: RoundedRectangle(cornerRadius: 18))
            Button(action: action == .pause ? { stop?() } : action == .restart ? { resume?() } : send) {
                Image(systemName: action == .pause ? "pause.fill" : action == .restart ? "play.fill" : "arrow.up")
                    .font(.system(size: 18, weight: .semibold)).foregroundStyle(.white)
                    .frame(width: 44, height: 44).background(theme.colors.sendButtonBackground, in: Circle())
            }.disabled(disabled || action == .unavailable)
                .opacity(disabled || action == .unavailable ? 0.4 : 1)
                .accessibilityLabel(buttonLabel)
        }.padding(.horizontal, 12).padding(.vertical, 8).background(theme.colors.mainBG)
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
