import SwiftUI
import CarryOnCore

enum Design {
    static let canvas = Color(uiColor: .systemBackground)
    static let background = neutral(light: 0.97, dark: 0.07)
    static let surface = neutral(light: 1, dark: 0.12)
    static let input = neutral(light: 0.95, dark: 0.16)
    static let ink = Color.primary
    static let secondary = Color.secondary
    static let border = Color.primary.opacity(0.10)
    static let onAccent = Color(uiColor: .systemBackground)
    static let blue = Color(uiColor: .systemBlue)
    static let green = Color(uiColor: .systemGreen)
    static let link = Color(uiColor: .link)
    static let orange = Color(uiColor: .systemOrange)
    static let corner: CGFloat = 16
    static let controlCorner: CGFloat = 14
    static let pageInset: CGFloat = 20

    private static func neutral(light: CGFloat, dark: CGFloat) -> Color {
        Color(uiColor: UIColor { traits in
            UIColor(white: traits.userInterfaceStyle == .dark ? dark : light, alpha: 1)
        })
    }
}

struct Paper<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View { VStack(spacing: 0) { content }.background(Design.surface, in: RoundedRectangle(cornerRadius: Design.corner)) }
}
struct SectionCaption: View {
    let title: String
    var body: some View { Text(title).font(.caption).foregroundStyle(Design.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 12).padding(.top, 16).padding(.bottom, 6) }
}
struct SymbolTile: View {
    let name: String
    var color = Design.secondary
    var body: some View { Image(systemName: name).font(.system(size: 20, weight: .regular)).foregroundStyle(color).frame(width: 38, height: 38) }
}
struct CountPill: View {
    let text: String
    var color = Design.secondary
    var body: some View { Text(text).font(.caption2.weight(.medium)).foregroundStyle(color).padding(.horizontal, 6).padding(.vertical, 4).background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 8)) }
}
struct SearchField: View {
    @Binding var text: String
    var placeholder = "搜索项目"
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(Design.secondary)
            TextField(placeholder, text: $text).font(.body).textInputAutocapitalization(.never).autocorrectionDisabled().submitLabel(.search)
            if !text.isEmpty { Button { text = "" } label: { Image(systemName: "xmark.circle.fill") }.accessibilityLabel("清除搜索") }
        }.padding(.horizontal, 11).frame(minHeight: 44).background(Design.input, in: RoundedRectangle(cornerRadius: Design.controlCorner))
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
    var imageName: String? = nil
    var body: some View {
        HStack(spacing: 12) {
            if let imageName {
                Image(imageName).resizable().scaledToFit().frame(width: 38, height: 38).accessibilityHidden(true)
            } else {
                SymbolTile(name: icon)
            }
            Text(title).font(.body).foregroundStyle(Design.ink)
            Spacer(minLength: 8)
            if badgeCount > 0 {
                Text(String(badgeCount)).font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                    .padding(.horizontal, 6).frame(minWidth: 20, minHeight: 20).background(.red, in: Capsule())
                    .accessibilityLabel("\(badgeCount) 项待确认")
            }
            Text(value).font(.subheadline).foregroundStyle(Design.secondary).multilineTextAlignment(.trailing)
            if chevron { Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary) }
        }.padding(14).frame(minHeight: 62).contentShape(Rectangle())
    }
}
struct ThreadRow: View {
    @Environment(AppModel.self) private var model
    let record: Record
    var dimmed = false
    private var projectName: String {
        if let name = record.value["projectName"].string, !name.isEmpty { return name }
        if record.value["projectless"].bool == true { return "最近" }
        let path = record.value["projectRoot"].string ?? record.value["projectKey"].string ?? record.value["cwd"].text
        return path.split(separator: "/").last.map(String.init) ?? "最近"
    }
    var body: some View {
        let state = record.value["status"]["state"].text
        HStack(spacing: 13) {
            SymbolTile(name: "bubble.left.and.bubble.right", color: state == "running" && model.connected ? Design.green : Design.secondary)
            VStack(alignment: .leading, spacing: 5) {
                HStack { Text(record.title).font(.body.weight(.medium)).lineLimit(2)
                    if record.value["unread"].bool == true { Circle().fill(Design.blue).frame(width: 7, height: 7).accessibilityLabel("未读") }
                }
                Text(projectName).font(.caption).foregroundStyle(Design.secondary).lineLimit(1)
                Text(record.value["failed"].bool == true ? "执行失败" : record.value["status"]["label"].string ?? "状态未知")
                    .font(.caption).foregroundStyle(state == "waiting" ? Design.orange : state == "running" ? Design.green : Design.secondary)
                if case .number(let time) = (state == "idle" && record.value["completedAt"] != .null ? record.value["completedAt"] : record.value["updated_at"]) {
                    Text(Date(timeIntervalSince1970: time), style: .relative)
                        .font(.caption).foregroundStyle(Design.secondary)
                }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
        }.padding(.horizontal, 15).padding(.vertical, 14).frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
            .saturation(dimmed ? 0 : 1).opacity(dimmed ? 0.5 : 1)
    }
}
