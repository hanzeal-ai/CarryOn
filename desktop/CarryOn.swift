import SwiftUI
import AppKit

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillTerminate(_ notification: Notification) { ForegroundServices.shared.terminateAll() }
}
#if !DESKTOP_TEST
@main struct CarryOnApp: App {
    @Environment(\.openWindow) private var openWindow
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        WindowGroup("CarryOn") { SettingsView(model: SettingsModel()) }
            .defaultSize(width: 1040, height: 790)
            .commands {
                CommandGroup(after: .appInfo) { Button("检查更新…") { openWindow(id: "app-updates") } }
            }
        Window("软件更新", id: "app-updates") { DesktopAppUpdateView() }
            .windowResizability(.contentSize)
    }
}
#endif
