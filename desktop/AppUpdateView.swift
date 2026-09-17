import SwiftUI
import AppKit

@MainActor struct DesktopAppUpdateView: View {
    @StateObject private var updater: AppUpdateModel
    init(updater: AppUpdateModel? = nil) { _updater = StateObject(wrappedValue: updater ?? AppUpdateModel(platform: .macOS)) }
    var body: some View {
        DesktopAppUpdateContent(updater: updater).task { await updater.check() }
    }
}

@MainActor struct DesktopAppUpdateContent: View {
    @ObservedObject var updater: AppUpdateModel
    @State private var openFailed = false
    var body: some View {
        VStack(spacing: 18) {
            if let url = Bundle.main.url(forResource: "CarryOnLogo", withExtension: "png"), let logo = NSImage(contentsOf: url) {
                Image(nsImage: logo).resizable().scaledToFit().frame(width: 64, height: 64)
            }
            Text("CarryOn").font(.title2.bold())
            Text("当前版本 " + updater.currentVersion).foregroundStyle(.secondary)
            switch updater.state {
            case .idle, .checking: ProgressView("正在检查更新…")
            case .failed(let message): Text(message).foregroundStyle(.secondary).multilineTextAlignment(.center)
            case .checked(.unavailable): Text("尚未发布可用版本").foregroundStyle(.secondary)
            case .checked(.current): Text("已是最新版本").foregroundStyle(.secondary)
            case .checked(.requiresSystem(let release)):
                Text("版本 \(release.versionLabel) 需要 macOS \(release.minimumSystemVersion) 或更高版本").multilineTextAlignment(.center)
            case .checked(.available(let release)):
                Text("发现新版本 " + release.versionLabel).font(.headline)
                if !release.notes.isEmpty { ScrollView { Text(release.notes).frame(maxWidth: .infinity, alignment: .leading) }.frame(height: 120) }
                Button(release.actionTitle) { openFailed = !NSWorkspace.shared.open(release.url) }.buttonStyle(.borderedProminent)
                Text("下载后打开 DMG，将 CarryOn 拖入“应用程序”替换旧版本。").font(.caption).foregroundStyle(.secondary)
            }
            if openFailed { Text("无法打开下载页面，请稍后重试").font(.caption).foregroundStyle(.red) }
            Button("重新检查") { Task { openFailed = false; await updater.check() } }.disabled(updater.state == .checking)
        }.padding(30).frame(width: 420).frame(minHeight: 290)
    }
}
