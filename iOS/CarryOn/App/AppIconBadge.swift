import UserNotifications
import OSLog

@MainActor final class AppIconBadge {
    private let center = UNUserNotificationCenter.current()
    private let logger = Logger(subsystem: "CarryOn", category: "AppIconBadge")
    private var count = 0
    private var mayRequestAuthorization = false
    private var revision = 0
    private var worker: Task<Void, Never>?

    func update(_ count: Int, requestAuthorization: Bool) {
        self.count = max(0, count)
        mayRequestAuthorization = requestAuthorization
        revision += 1
        guard worker == nil else { return }
        worker = Task { await synchronize() }
    }

    private func synchronize() async {
        defer { worker = nil }
        while true {
            let version = revision
            do {
                let settings = await center.notificationSettings()
                guard version == revision else { continue }
                if settings.authorizationStatus == .notDetermined && mayRequestAuthorization {
                    _ = try await center.requestAuthorization(options: [.badge])
                    guard version == revision else { continue }
                }
                // Serialize writes so an older count cannot finish after a newer count.
                try await center.setBadgeCount(count)
            } catch {
                if version == revision { logger.error("Unable to synchronize app icon badge: \(error.localizedDescription, privacy: .public)") }
            }
            if version == revision { return }
        }
    }
}
