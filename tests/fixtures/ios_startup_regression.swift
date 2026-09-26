import SwiftUI
import CarryOnCore

@main struct StartupRegressionApp: App {
    @State private var fixture = StartupFixture()
    var body: some Scene {
        WindowGroup {
            ZStack { RootView().environment(fixture.model) }
                .task { await fixture.run() }
        }
    }
}

@MainActor @Observable final class StartupFixture: NSObject {
    var model = AppModel()
    private var started = false
    private var displayLink: CADisplayLink?
    private var ticks: [Double] = []
    private var checks: [String: Bool] = [:]
    private let server = "https://startup.carryon.test/"
    private let vault = KeychainSessionCredentials()

    func run() async {
        guard !started else { return }
        started = true
        do {
            let savedServer = UserDefaults.standard.string(forKey: "carryon.server")
            UserDefaults.standard.removeObject(forKey: "carryon.server")
            checks["freshInstallHasOfficialServer"] = try ConsoleAddress(AppModel().addressText) == ConsoleAddress("https://carryon.hanzeal.com/")
            UserDefaults.standard.set("", forKey: "carryon.server")
            checks["emptySavedServerUsesOfficialServer"] = try ConsoleAddress(AppModel().addressText) == ConsoleAddress("https://carryon.hanzeal.com/")
            UserDefaults.standard.set(server, forKey: "carryon.server")
            checks["customServerIsPreserved"] = AppModel().addressText == server
            if let savedServer { UserDefaults.standard.set(savedServer, forKey: "carryon.server") }
            else { UserDefaults.standard.removeObject(forKey: "carryon.server") }
            model.addressText = ""
            let firstStart = ContinuousClock.now
            await model.restoreLogin()
            checks["noAccountShowsLogin"] = !model.restoringLogin && !model.authenticated && model.restorationError == nil
            checks["noAccountReadyUnderOneSecond"] = firstStart.duration(to: .now) < .seconds(1)

            try vault.save("fixture-session", server: server)
            model = AppModel(); model.addressText = server
            StartupProtocol.mode = "stall"
            try await Task.sleep(for: .milliseconds(300))
            displayLink = CADisplayLink(target: self, selector: #selector(sample))
            displayLink?.add(to: .main, forMode: .common)
            let start = ContinuousClock.now
            let stalledRestore = Task { await self.model.restoreLogin() }
            try await Task.sleep(for: .milliseconds(250))
            if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
                let snapshot = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in
                    window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
                }
                try snapshot.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("startup-waiting.png"))
            }
            checks["waitingDoesNotAuthenticateOrEnableWrites"] = model.restoringLogin && !model.authenticated && !model.canWrite
            await stalledRestore.value
            let elapsed = start.duration(to: .now)
            displayLink?.invalidate(); displayLink = nil
            let gaps = zip(ticks, ticks.dropFirst()).map { $1 - $0 }
            checks["stalledSessionHasTenSecondDeadline"] = elapsed >= .seconds(9.5) && elapsed < .seconds(12)
            checks["UIContinuesDrawingWhileWaiting"] = ticks.count > 100 && (gaps.max() ?? 1) < 0.5
            checks["failureExposesRetryWithoutAuthenticating"] = model.restorationError != nil && !model.restoringLogin && !model.busy && !model.authenticated
            checks["timeoutPreservesCredential"] = try vault.load(server: server) == "fixture-session"

            StartupProtocol.mode = "success"
            await model.restoreLogin()
            checks["retryRestoresAuthenticatedHome"] = model.authenticated && !model.restoringLogin && model.restorationError == nil
            let emptyEpoch = model.epoch, emptyRevision = model.workspaceRevision
            try await model.refreshDirectory()
            try await model.refreshDirectory()
            checks["emptyDirectoryDoesNotRestartWorkspace"] = model.epoch == emptyEpoch && model.workspaceRevision == emptyRevision
            checks["emptyDirectoryKeepsBindingRequestsReadable"] = try await model.console("binding/pending")["requests"].array.isEmpty
            model.setForeground(false)

            model = AppModel(); model.addressText = server
            StartupProtocol.mode = "expired"
            await model.restoreLogin()
            checks["expiredSessionReturnsToLogin"] = !model.authenticated && !model.restoringLogin && model.restorationError == nil
            checks["expiredCredentialRemoved"] = try vault.load(server: server) == nil

            try vault.save("fixture-session", server: server)
            model = AppModel(); model.addressText = server
            StartupProtocol.mode = "stall"
            let restoring = Task { await self.model.restoreLogin() }
            try await Task.sleep(for: .milliseconds(100))
            restoring.cancel(); await restoring.value
            checks["cancelledRestoreDoesNotAuthenticate"] = !model.authenticated && !model.busy && !model.restoringLogin && model.restorationError == nil
            checks["cancellationPreservesCredential"] = try vault.load(server: server) == "fixture-session"
            StartupProtocol.mode = "interactive"
            model.addressText = server
            let result: [String: Any] = ["passed": checks.values.allSatisfy { $0 }, "checks": checks,
                                       "framesDuringStall": ticks.count, "maxFrameGapSeconds": gaps.max() ?? 0]
            let output = URL.documentsDirectory.appendingPathComponent("startup-result.json")
            try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: output)
            print("STARTUP_REGRESSION_COMPLETE \(output.path)")
        } catch {
            let result: [String: Any] = ["passed": false, "checks": checks, "error": error.localizedDescription]
            try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted]).write(to: URL.documentsDirectory.appendingPathComponent("startup-result.json"))
            print("STARTUP_REGRESSION_FAILED \(error)")
        }
    }
    @objc private func sample() { ticks.append(CACurrentMediaTime()) }
}
