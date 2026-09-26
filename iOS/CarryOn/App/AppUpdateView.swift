import SwiftUI
import CarryOnCore

struct AppUpdateView: View {
    @ObservedObject var updater: AppUpdateModel
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var openFailed = false
    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Image("CarryOnLogo").resizable().scaledToFit().frame(width: 64, height: 64)
                Text("CarryOn").font(.title2.bold())
                Text("当前版本 " + updater.currentVersion).foregroundStyle(Design.secondary)
                switch updater.state {
                case .idle, .checking: ProgressView("正在检查更新…")
                case .failed(let message): Text(message).foregroundStyle(Design.secondary).multilineTextAlignment(.center)
                case .checked(.unavailable): Text("尚未发布可用版本").foregroundStyle(Design.secondary)
                case .checked(.current): Text("已是最新版本").foregroundStyle(Design.secondary)
                case .checked(.requiresSystem(let release)):
                    Text("版本 \(release.versionLabel) 需要 iOS \(release.minimumSystemVersion) 或更高版本").multilineTextAlignment(.center)
                case .checked(.available(let release)):
                    Text("发现新版本 " + release.versionLabel).font(.headline)
                    if !release.notes.isEmpty { ScrollView { Text(release.notes).frame(maxWidth: .infinity, alignment: .leading) }.frame(maxHeight: 200) }
                    Button(release.actionTitle) { openURL(release.url) { openFailed = !$0 } }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent)
                }
                if openFailed { Text("无法打开更新页面，请稍后重试").font(.caption).foregroundStyle(.red) }
                Button("重新检查") { Task { openFailed = false; await updater.check() } }.disabled(updater.state == .checking)
            }.padding(28).frame(maxWidth: .infinity, maxHeight: .infinity).background(Design.background)
                .navigationTitle("软件更新").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
        }.task { await updater.check() }
    }
}
