import SwiftUI

enum DesktopDesign {
    static let background = Color(nsColor: .windowBackgroundColor)
    static let ink = Color.primary
    static let secondary = Color.secondary
    static let blue = Color.primary
    static let green = Color(red: 0.145, green: 0.518, blue: 0.255)
    static let line = Color.primary.opacity(0.10)
}
struct Paper<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View { VStack(spacing: 0) { content }.frame(maxWidth: .infinity).background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 19)) }
}
struct SectionCaption: View {
    let title: String
    var body: some View { Text(title).font(.system(size: 12, weight: .medium)).foregroundStyle(DesktopDesign.secondary).frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 12).padding(.top, 22).padding(.bottom, 8) }
}
struct SymbolTile: View {
    let name: String
    var color = DesktopDesign.secondary
    var body: some View { Image(systemName: name).font(.system(size: 17)).foregroundStyle(color).frame(width: 36, height: 36).background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 12)) }
}
struct SettingRow<Accessory: View>: View {
    let icon: String
    let title: String
    var detail = ""
    @ViewBuilder var accessory: Accessory
    var body: some View {
        HStack(spacing: 12) {
            SymbolTile(name: icon)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 14, weight: .medium))
                if !detail.isEmpty { Text(detail).font(.system(size: 11)).foregroundStyle(DesktopDesign.secondary).lineLimit(2) }
            }
            Spacer(minLength: 12); accessory
        }.padding(.horizontal, 16).padding(.vertical, 13).frame(minHeight: 62).contentShape(Rectangle())
    }
}
struct RowDivider: View { var body: some View { Rectangle().fill(DesktopDesign.line).frame(height: 1).padding(.leading, 64) } }
struct StatePill: View {
    let label: String
    var active = false
    var body: some View {
        HStack(spacing: 5) { Circle().fill(active ? DesktopDesign.green : DesktopDesign.secondary).frame(width: 6, height: 6); Text(label).font(.system(size: 11)) }
            .foregroundStyle(active ? DesktopDesign.green : DesktopDesign.secondary).padding(.horizontal, 9).padding(.vertical, 5)
            .background((active ? DesktopDesign.green : DesktopDesign.secondary).opacity(0.07), in: Capsule())
    }
}
struct AccentButton: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 13, weight: .semibold)).foregroundStyle(Color(nsColor: .windowBackgroundColor))
            .padding(.horizontal, 17).frame(height: 36).background(isEnabled ? DesktopDesign.blue.opacity(configuration.isPressed ? 0.7 : 1) : DesktopDesign.secondary.opacity(0.35), in: RoundedRectangle(cornerRadius: 12))
    }
}
struct QuietButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 12, weight: .medium)).foregroundStyle(DesktopDesign.blue)
            .padding(.horizontal, 12).frame(height: 32).background(DesktopDesign.blue.opacity(configuration.isPressed ? 0.13 : 0.06), in: RoundedRectangle(cornerRadius: 12))
    }
}
