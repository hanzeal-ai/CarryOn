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
                else if fixture.screen == 5 { ActivityView() }
                else if fixture.screen == 6 {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            WorkspaceBindingRequests()
                            MessageMarkdown(text: "正文 **强调**、`行内代码` 和 [链接](https://example.com)。\n\n> 引用内容\n\n```swift\nlet result = \"完成\"\n```", resolveCreatedThreads: false)
                        }.padding(20)
                    }.background(Design.background)
                }
                else { Color.white }
            }.environment(fixture.model).tint(Design.ink).preferredColorScheme(fixture.dark ? .dark : .light).task { await fixture.run() }
        }
    }
}
@MainActor @Observable final class CacheFixture {
    let model = AppModel()
    var screen = 0
    var dark = false
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
            UserDefaults.standard.removeObject(forKey: "carryon.showInactiveConversations")
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
            checks["projectReentryReusesRows"] = CacheProtocol.count("/api/projects?limit=50&offset=0&search=&filter=all&availableOnly=true") == 1
            UserDefaults.standard.set(true, forKey: "carryon.showInactiveConversations")
            await pause()
            checks["showInactiveRefreshesGlobalList"] = CacheProtocol.count("/api/projects?limit=50&offset=0&search=&filter=all&availableOnly=false") == 1
            UserDefaults.standard.set(false, forKey: "carryon.showInactiveConversations")
            await pause()

            let thread = try Record(.object(["id": .string("running-0"), "title": .string("执行中任务")]))
            let cached = model.displayCache.value(model.historyCacheKey(thread.id))
            model.open(thread)
            checks["openDisplaysPrefetchedMessagesSynchronously"] = cached != .null && model.history == cached
            checks["cacheDoesNotAuthorizeOrMarkRead"] = !model.connected && !model.canWrite && model.readSequence == 0
            screen = 3; await pause(); try capture("cache-conversation")
            let retainedSocket = CacheSocket.connectionIDs(for: thread.id)
            let retainedSubscriptions = CacheSocket.subscriptionCount(for: thread.id)
            let beforeBackground = model.history["historyRevision"]
            model.setForeground(false); await pause()
            checks["backgroundStopsAdditionalStreams"] = CacheSocket.activeCount == 1
            checks["backgroundContinuesCurrentHistory"] = model.history["historyRevision"] != beforeBackground
            model.setForeground(true)
            checks["shortResumeDoesNotShowReconnect"] = model.connected && !model.reconnecting
            await pause()
            checks["shortResumeReusesConnectionAndSubscription"] = !retainedSocket.isEmpty
                && CacheSocket.connectionIDs(for: thread.id) == retainedSocket
                && CacheSocket.subscriptionCount(for: thread.id) == retainedSubscriptions
            model.setForeground(false)
            model.expireBackgroundSync(); model.expireBackgroundSync()
            await pause()
            checks["expirationClosesStreamsAndDoesNotReconnectInBackground"] = CacheSocket.activeCount == 0 && !model.connected
            model.setForeground(true)
            checks["expiredResumeShowsReconnect"] = !model.connected && model.reconnecting
            await pause(); await pause()
            checks["expiredResumeReopensAndSynchronizes"] = model.connected
                && !CacheSocket.connectionIDs(for: thread.id).isEmpty
                && CacheSocket.connectionIDs(for: thread.id) != retainedSocket
                && model.history["thread"]["id"].text == thread.id
            model.setForeground(false)
            model.switchDevice("other"); model.open(thread)
            checks["workspaceIsolation"] = model.history == .null
            model.switchDevice("fixture"); model.open(thread)
            checks["returnToWorkspaceRetainsMessages"] = model.history != .null
            let noticeA = "00000000-0000-0000-0000-000000000001"
            let noticeB = "00000000-0000-0000-0000-000000000002"
            func notification(_ id: String) -> PushTarget {
                PushTarget(server: model.addressText, deviceID: "fixture", threadID: id, eventID: id)!
            }
            let pathA = "/api/workspace/threads?threadId=" + noticeA
            func waitForRequest(_ count: Int) async {
                for _ in 0..<100 {
                    if CacheProtocol.count(pathA) > count { return }
                    try? await Task.sleep(for: .milliseconds(10))
                }
            }
            var beforeNotice = CacheProtocol.count(pathA)
            let first = Task { await model.openNotification(notification(noticeA)) }
            await waitForRequest(beforeNotice)
            model.open(thread)
            await first.value
            checks["lateNotificationDoesNotOverrideManualNavigation"] = CacheProtocol.count(pathA) > beforeNotice && model.selectedThread?.id == thread.id
            beforeNotice = CacheProtocol.count(pathA)
            let older = Task { await model.openNotification(notification(noticeA)) }
            await waitForRequest(beforeNotice)
            let newer = Task { await model.openNotification(notification(noticeB)) }
            await older.value; await newer.value
            checks["newerNotificationWins"] = CacheProtocol.count(pathA) > beforeNotice && model.selectedThread?.id == noticeB
            let notificationDiagnostic: [String: Any] = ["selected": model.selectedThread?.id ?? "", "error": model.error ?? "", "aRequests": CacheProtocol.count(pathA), "bRequests": CacheProtocol.count("/api/workspace/threads?threadId=" + noticeB)]
            model.open(thread)
            await model.displayCache.flush()
            let reopened = AppModel(); reopened.addressText = model.addressText; reopened.foreground = false
            await reopened.restoreLogin(); reopened.open(thread)
            checks["restartRestoresRecentMessages"] = reopened.history != .null && !reopened.connected
            await reopened.logout()
            checks["logoutClearsVisibleCache"] = reopened.displayCache.value(reopened.historyCacheKey(thread.id)) == .null
            screen = 0
            model.setForeground(false); model.expireBackgroundSync()
            await pause()
            model.selectedThread = try Record(.object(["id": .string("activity-completed")]))
            model.connected = true; model.status = .object(["enabled": .bool(true)])
            UserDefaults.standard.set(false, forKey: "carryon.showInactiveConversations")
            try await model.refreshActivityCounts()
            checks["activityCountsHideInactive"] = model.activityCount == 1 && model.otherActivityCount == 0
            UserDefaults.standard.set(true, forKey: "carryon.showInactiveConversations")
            try await model.refreshActivityCounts()
            checks["activityCountsIncludeInactiveWhenEnabled"] = model.activityCount == 2 && model.otherActivityCount == 1
            UserDefaults.standard.set(false, forKey: "carryon.showInactiveConversations")
            model.selectedThread = nil
            screen = 6; await pause(); try capture("theme-light")
            dark = true; await pause(); try capture("theme-dark")
            screen = 1; await pause(); try capture("settings-dark")
            screen = 5; await pause(); try capture("activity-dark")
            let result: [String: Any] = ["notificationDiagnostic": notificationDiagnostic, "passed": checks.values.allSatisfy { $0 }, "checks": checks]
            try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("cache-result.json"))
        } catch {
            try? JSONSerialization.data(withJSONObject: ["passed": false, "checks": checks, "error": error.localizedDescription]).write(to: URL.documentsDirectory.appendingPathComponent("cache-result.json"))
        }
    }
}
