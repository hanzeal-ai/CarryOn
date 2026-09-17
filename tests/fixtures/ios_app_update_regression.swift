import SwiftUI
import CarryOnCore

@main struct AppUpdateRegression: App {
    @StateObject private var updater = AppUpdateModel(platform: .iOS)
    var body: some Scene {
        WindowGroup { AppUpdateView(updater: updater).task { await verify() } }
    }
    @MainActor private func verify() async {
        var checks: [String: Bool] = [:]
        for mode in ["available", "current", "unpublished", "failure", "incompatible"] {
            AppUpdateFixtureProtocol.mode = mode
            // Let the initial view-owned check finish before advancing the injected response.
            try? await Task.sleep(for: .milliseconds(200))
            await updater.check()
            switch (mode, updater.state) {
            case ("available", .checked(.available)), ("current", .checked(.current)), ("unpublished", .checked(.unavailable)),
                 ("failure", .failed), ("incompatible", .checked(.requiresSystem)): checks[mode] = true
            default: checks[mode] = false
            }
            try? await Task.sleep(for: .milliseconds(500))
            if ["available", "unpublished"].contains(mode), let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
                let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
                try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("app-update-\(mode).png"))
            }
        }
        checks["currentVersionFromBundle"] = updater.currentVersion == "1.0 (3)"
        try? JSONSerialization.data(withJSONObject: ["passed": checks.values.allSatisfy { $0 }, "checks": checks], options: [.prettyPrinted, .sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("app-update-result.json"))
    }
}
