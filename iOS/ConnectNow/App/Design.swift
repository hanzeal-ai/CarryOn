import SwiftUI
import ConnectNowCore

enum Design {
    static let background = Color(red: 0.949, green: 0.949, blue: 0.969)
    static let ink = Color(red: 0.11, green: 0.11, blue: 0.12)
    static let secondary = Color(red: 0.43, green: 0.43, blue: 0.45)
    static let blue = Color(red: 0, green: 0.40, blue: 0.875)
    static let green = Color(red: 0.145, green: 0.518, blue: 0.255)
    static let orange = Color(red: 0.65, green: 0.38, blue: 0.03)
}
struct Paper<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View { VStack(spacing: 0) { content }.background(.white, in: RoundedRectangle(cornerRadius: 19)) }
}
struct SectionCaption: View {
    let title: String
    var body: some View { Text(title).font(.caption).foregroundStyle(Design.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 12).padding(.top, 16).padding(.bottom, 6) }
}
struct SymbolTile: View {
    let name: String
    var color = Design.secondary
    var body: some View { Image(systemName: name).font(.system(size: 19, weight: .regular)).foregroundStyle(color).frame(width: 38, height: 38).background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 10)) }
}
struct CountPill: View {
    let text: String
    var color = Design.secondary
    var body: some View { Text(text).font(.system(size: 11)).foregroundStyle(color).padding(.horizontal, 6).padding(.vertical, 4).background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 6)) }
}
struct SearchField: View {
    @Binding var text: String
    var placeholder = "搜索项目"
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(Design.secondary)
            TextField(placeholder, text: $text).font(.system(size: 16)).textInputAutocapitalization(.never).autocorrectionDisabled().submitLabel(.search)
            if !text.isEmpty { Button { text = "" } label: { Image(systemName: "xmark.circle.fill") }.accessibilityLabel("清除搜索") }
        }.padding(.horizontal, 11).frame(minHeight: 40).background(Color.black.opacity(0.055), in: RoundedRectangle(cornerRadius: 12))
    }
}
struct BlankState: View {
    let text: String
    var loading = false
    var symbol = "tray"
    var detail: String?
    var retry: (() -> Void)?
    var body: some View {
        Group {
            if loading {
                ProgressView { Text(text).font(.subheadline).foregroundStyle(Design.secondary) }
                    .frame(maxWidth: .infinity).padding(.vertical, 55)
            } else {
                ContentUnavailableView {
                    Label(text, systemImage: symbol)
                } description: {
                    if let detail { Text(detail) }
                } actions: {
                    if let retry { Button("重试", action: retry).buttonStyle(.bordered) }
                }
            }
        }.accessibilityElement(children: .contain)
    }
}
struct SettingRow: View {
    let icon: String
    let title: String
    var value = ""
    var chevron = false
    var badgeCount = 0
    var body: some View {
        HStack(spacing: 12) {
            SymbolTile(name: icon)
            Text(title).font(.system(size: 15)).foregroundStyle(Design.ink)
            Spacer(minLength: 8)
            if badgeCount > 0 {
                Text(String(badgeCount)).font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                    .padding(.horizontal, 6).frame(minWidth: 20, minHeight: 20).background(.red, in: Capsule())
                    .accessibilityLabel("\(badgeCount) 项待确认")
            }
            Text(value).font(.system(size: 13)).foregroundStyle(Design.secondary).multilineTextAlignment(.trailing)
            if chevron { Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary) }
        }.padding(14).frame(minHeight: 62).contentShape(Rectangle())
    }
}
struct ThreadRow: View {
    let record: Record
    var body: some View {
        let state = record.value["status"]["state"].text
        HStack(spacing: 13) {
            SymbolTile(name: state == "waiting" ? "lock" : state == "running" ? "chevron.left.forwardslash.chevron.right" : "bubble", color: state == "waiting" ? Design.orange : state == "running" ? Design.green : Design.secondary)
            VStack(alignment: .leading, spacing: 7) {
                HStack { Text(record.title).font(.system(size: 15, weight: .semibold)).lineLimit(2)
                    if record.value["unread"].bool == true { Circle().fill(Design.blue).frame(width: 7, height: 7).accessibilityLabel("未读") }
                }
                Text(record.value["cwd"].text).font(.caption2).foregroundStyle(Design.secondary).lineLimit(1)
                Text(record.value["failed"].bool == true ? "执行失败" : record.value["status"]["label"].string ?? "状态未知")
                    .font(.caption2).foregroundStyle(state == "waiting" ? Design.orange : state == "running" ? Design.green : Design.secondary)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
        }.padding(.horizontal, 15).padding(.vertical, 17).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
    }
}

// A non-cancelling window tap preserves buttons, selection and native scrolling.
struct KeyboardDismissal: UIViewRepresentable {
    func makeUIView(context: Context) -> KeyboardDismissView { KeyboardDismissView() }
    func updateUIView(_ uiView: KeyboardDismissView, context: Context) {}
}
final class KeyboardDismissView: UIView, UIGestureRecognizerDelegate {
    private var tap: UITapGestureRecognizer?
    override func didMoveToWindow() {
        super.didMoveToWindow()
        if let tap { tap.view?.removeGestureRecognizer(tap) }
        guard let window else { return }
        let recognizer = UITapGestureRecognizer(target: self, action: #selector(dismissKeyboard))
        recognizer.cancelsTouchesInView = false; recognizer.delegate = self
        window.addGestureRecognizer(recognizer); tap = recognizer
    }
    @objc private func dismissKeyboard() { window?.endEditing(true) }
    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        var view = touch.view
        while let current = view {
            if current is UIControl || current is UITextView { return false }
            view = current.superview
        }
        return true
    }
    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool { true }
}
