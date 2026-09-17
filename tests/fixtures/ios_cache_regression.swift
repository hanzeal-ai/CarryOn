import SwiftUI
import CarryOnCore

@main struct CacheRegressionApp: App {
    @State private var fixture = CacheFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                if fixture.screen == 1 { SettingsView() }
                else if fixture.screen == 2, let device = fixture.model.device { WorkspaceDetails(device: device) }
                else if fixture.screen == 3, let thread = fixture.model.selectedThread { ConversationView(thread: thread) }
                else if fixture.screen == 4 { ProjectsView() }
                else { Color.white }
            }.environment(fixture.model).task { await fixture.run() }
        }
    }
}
@MainActor @Observable final class CacheFixture {
    let model = AppModel()
    var screen = 0
    private var started = false
    private var checks: [String: Bool] = [:]
    func pause() async { try? await Task.sleep(for: .milliseconds(650)) }
    func capture(_ name: String) throws {
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent(name + ".png"))
    }
    func run() async {
        guard !started else { return }; started = true
        do {
            model.addressText = "https://cache.carryon.test/"
            try KeychainSessionCredentials().save(UUID().uuidString, server: model.addressText)
            await model.restoreLogin()
            await pause(); await pause()
            checks["prefetchBeforeOpeningConversation"] = model.selectedThread == nil && model.displayCache.value(model.historyCacheKey("running-0")) != .null
            checks["threeBackgroundStreamsPlusMainMaximum"] = CacheSocket.activeCount == 4
            let revision = model.displayCache.value(model.historyCacheKey("running-0"))["historyRevision"]
            await pause()
            checks["unopenedConversationContinuesUpdating"] = model.displayCache.value(model.historyCacheKey("running-0"))["historyRevision"] != revision
            CacheProtocol.runningIDs = ["running-1", "running-2", "running-3"]
            try await model.refreshDirectory()
            checks["finishingStreamNotEvictedBeforeFinalSnapshot"] = CacheSocket.watchedThreads.contains("running-0") || model.displayCache.value(model.historyCacheKey("running-0"))["status"]["state"].text == "idle"
            model.open(try Record(.object(["id": .string("running-1"), "title": .string("当前任务")])))
            await pause()
            checks["tailSettlementDoesNotResubscribeSelectedConversation"] = CacheSocket.watchedThreads.filter { $0 == "running-1" }.count == 1
            model.closeThread()
            checks["finalSnapshotArrivesBeforeTailCloses"] = model.displayCache.value(model.historyCacheKey("running-0"))["status"]["state"].text == "idle"
            CacheProtocol.runningIDs = ["new-0", "new-1", "new-2"]
            try await model.refreshDirectory(); await pause(); await pause()
            checks["completedBatchReleasesSlotsForNewRunningTasks"] = Set(CacheSocket.watchedThreads) == Set(CacheProtocol.runningIDs)
            CacheProtocol.runningIDs = (0..<4).map { "running-\($0)" }
            try await model.refreshDirectory(); await pause(); await pause()
            screen = 1; await pause(); screen = 0; await pause(); screen = 1; await pause()
            checks["settingsReentryReusesStandby"] = CacheProtocol.count("/api/standby") == 1
            checks["settingsReentryReusesUsage"] = CacheProtocol.count("/api/usage") == 1
            try capture("cache-settings")
            screen = 2; await pause(); screen = 0; await pause(); screen = 2; await pause()
            checks["workspaceDetailsReentryReusesStatus"] = CacheProtocol.count("/api/status") == 1
            screen = 4; await pause(); screen = 0; await pause(); screen = 4; await pause()
            checks["projectReentryReusesRows"] = CacheProtocol.count("/api/projects?limit=50&offset=0&search=&filter=all") == 1
            let thread = try Record(.object(["id": .string("running-0"), "title": .string("执行中任务")]))
            let cached = model.displayCache.value(model.historyCacheKey(thread.id))
            model.open(thread)
            checks["openDisplaysPrefetchedMessagesSynchronously"] = cached != .null && model.history == cached
            checks["cacheDoesNotAuthorizeOrMarkRead"] = !model.connected && !model.canWrite && model.readSequence == 0
            screen = 3; await pause(); try capture("cache-conversation")
            model.setForeground(false); await pause()
            checks["backgroundStopsAdditionalStreams"] = CacheSocket.activeCount == 1
            model.switchDevice("other"); model.open(thread)
            checks["workspaceIsolation"] = model.history == .null
            model.switchDevice("fixture"); model.open(thread)
            checks["returnToWorkspaceRetainsMessages"] = model.history != .null
            await model.displayCache.flush()
            let reopened = AppModel(); reopened.addressText = model.addressText; reopened.foreground = false
            await reopened.restoreLogin(); reopened.open(thread)
            checks["restartRestoresRecentMessages"] = reopened.history != .null && !reopened.connected
            await reopened.logout()
            checks["logoutClearsVisibleCache"] = reopened.displayCache.value(reopened.historyCacheKey(thread.id)) == .null
            let result: [String: Any] = ["passed": checks.values.allSatisfy { $0 }, "checks": checks]
            try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("cache-result.json"))
        } catch {
            try? JSONSerialization.data(withJSONObject: ["passed": false, "checks": checks, "error": error.localizedDescription]).write(to: URL.documentsDirectory.appendingPathComponent("cache-result.json"))
        }
    }
}
