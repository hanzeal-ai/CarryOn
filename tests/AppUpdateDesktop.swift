import SwiftUI
import AppKit

@main @MainActor struct AppUpdateDesktopRegression {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let updater = AppUpdateModel(platform: .macOS, client: AppUpdateClient(configuration: AppUpdateFixtureProtocol.configuration))
        let view = NSHostingView(rootView: DesktopAppUpdateView(updater: updater))
        let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 420, height: 600), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.contentView = view; window.makeKeyAndOrderFront(nil)
        Task {
            var checks: [String: Bool] = ["logoResource": Bundle.main.url(forResource: "CarryOnLogo", withExtension: "png").flatMap { NSImage(contentsOf: $0) } != nil]
            let output = URL(fileURLWithPath: ProcessInfo.processInfo.environment["UPDATE_TEST_OUTPUT"]!)
            for mode in ["available", "current", "unpublished", "failure", "incompatible"] {
                AppUpdateFixtureProtocol.mode = mode
                try? await Task.sleep(for: .milliseconds(200))
                await updater.check()
                switch (mode, updater.state) {
                case ("available", .checked(.available)), ("current", .checked(.current)), ("unpublished", .checked(.unavailable)),
                     ("failure", .failed), ("incompatible", .checked(.requiresSystem)): checks[mode] = true
                default: checks[mode] = false
                }
                if mode == "available", case .checked(.available(let release)) = updater.state {
                    checks["releaseNotes"] = release.notes == "改善会话加载体验，修复工作区切换问题。"
                }
                try? await Task.sleep(for: .milliseconds(500))
                if ["available", "unpublished"].contains(mode) {
                    window.setContentSize(NSSize(width: 420, height: 600))
                    window.contentView?.layoutSubtreeIfNeeded()
                    window.displayIfNeeded()
                    try? await Task.sleep(for: .milliseconds(300))
                    if let capture = CGWindowListCreateImage(.null, .optionIncludingWindow, CGWindowID(window.windowNumber), [.boundsIgnoreFraming, .bestResolution]) {
                        let bitmap = NSBitmapImageRep(cgImage: capture)
                        try? bitmap.representation(using: .png, properties: [:])?.write(to: output.appendingPathComponent("\(mode)-window.png"))
                    }
                    let renderer = ImageRenderer(content: DesktopAppUpdateContent(updater: updater).background(Color.white))
                    renderer.scale = 2
                    if let image = renderer.nsImage, let data = image.tiffRepresentation,
                       let bitmap = NSBitmapImageRep(data: data) {
                        try? bitmap.representation(using: .png, properties: [:])?.write(to: output.appendingPathComponent("\(mode).png"))
                    }
                }
            }
            checks["currentVersionFromBundle"] = updater.currentVersion == "0.2.2"
            try? JSONSerialization.data(withJSONObject: ["passed": checks.values.allSatisfy { $0 }, "checks": checks], options: [.prettyPrinted, .sortedKeys]).write(to: output.appendingPathComponent("result.json"))
            app.terminate(nil)
        }
        app.run()
    }
}
