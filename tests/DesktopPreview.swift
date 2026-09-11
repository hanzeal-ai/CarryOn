import SwiftUI
import AppKit
@main struct DesktopPreview {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        Task { @MainActor in
            let model = SettingsModel()
            await model.refresh()
            let view = NSHostingView(rootView: SettingsView(model: model))
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 850), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            window.contentView = view
            window.makeKeyAndOrderFront(nil)
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            view.layoutSubtreeIfNeeded()
            window.display()
            if let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
                view.cacheDisplay(in: view.bounds, to: bitmap)
                try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: ProcessInfo.processInfo.environment["CONNECTNOW_PREVIEW_OUTPUT"]!))
            }
            app.terminate(nil)
        }
        app.run()
    }
}
