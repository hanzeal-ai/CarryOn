import SwiftUI
import AppKit

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillTerminate(_ notification: Notification) { ForegroundServices.shared.terminateAll() }
}
#if !DESKTOP_TEST
@main struct CarryOnApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        WindowGroup("CarryOn") { SettingsView(model: SettingsModel()) }
            .defaultSize(width: 1040, height: 790)
    }
}
#endif
