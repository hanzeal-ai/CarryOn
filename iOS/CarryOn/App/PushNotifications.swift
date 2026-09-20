import UIKit
import UserNotifications
import CarryOnCore

@MainActor final class PushNotifications: NSObject, ObservableObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    @Published private(set) var token: String?
    @Published var target: PushTarget?
    @Published private(set) var registrationError: String?
    let installationID: String = {
        if let id = UserDefaults.standard.string(forKey: "carryon.push.installation"), UUID(uuidString: id) != nil { return id }
        let id = UUID().uuidString.lowercased()
        UserDefaults.standard.set(id, forKey: "carryon.push.installation")
        return id
    }()
    private var synchronized = ""

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        token = deviceToken.map { String(format: "%02x", $0) }.joined(); registrationError = nil
    }
    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        registrationError = error.localizedDescription
    }
    static func nextRevision() throws -> JSONValue {
        let key = "carryon.push.registrationRevision"
        let previous = UserDefaults.standard.integer(forKey: key)
        guard previous >= 0, previous < 9_007_199_254_740_991 else { throw APIError("推送注册版本异常") }
        let next = previous + 1
        UserDefaults.standard.set(next, forKey: key)
        return .number(Double(next))
    }
    func synchronize(model: AppModel) async {
        let scope = model.scope
        for attempt in 0..<3 {
            do {
                try Task.checkCancellation()
                guard scope == model.scope else { return }
                try await synchronizeOnce(model: model)
                return
            } catch {
                if Task.isCancelled || error is CancellationError { return }
                if let status = (error as? APIError)?.status, [400, 401, 403].contains(status) {
                    model.report(error, operation: "注册系统通知", blocking: false); return
                }
                if attempt == 2 { model.report(error, operation: "注册系统通知", blocking: false); return }
                do { try await Task.sleep(for: .seconds(attempt == 0 ? 1 : 3)) } catch { return }
            }
        }
    }
    private func synchronizeOnce(model: AppModel) async throws {
        guard model.authenticated, !model.selectedDevice.isEmpty else { synchronized = ""; return }
        let scope = model.scope
        let available = try await model.console("push")
        try Task.checkCancellation()
        guard model.authenticated, scope == model.scope, available["enabled"].bool == true else { return }
        let center = UNUserNotificationCenter.current()
        var settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try await center.requestAuthorization(options: [.alert, .sound, .badge])
            settings = await center.notificationSettings()
        }
        try Task.checkCancellation()
        guard model.authenticated, scope == model.scope else { return }
        if settings.authorizationStatus == .denied {
            _ = try await model.console("push", body: .object(["installationId": .string(installationID), "revision": try Self.nextRevision()]), method: "DELETE")
            synchronized = ""; return
        }
        guard [.authorized, .provisional, .ephemeral].contains(settings.authorizationStatus) else { return }
        UIApplication.shared.registerForRemoteNotifications()
        guard let token else { return }
        let key = model.scope + token
        guard synchronized != key else { return }
        let environment = Bundle.main.object(forInfoDictionaryKey: "CarryOnAPNsEnvironment") as? String ?? "sandbox"
        let response = try await model.console("push", body: .object([
            "revision": try Self.nextRevision(),
            "installationId": .string(installationID), "token": .string(token),
            "environment": .string(environment), "deviceId": .string(model.selectedDevice)
        ]))
        guard key == model.scope + (self.token ?? "") else { return }
        guard response["registered"].bool == true else { return }
        synchronized = key
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                             withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        // In-app activity and badges already represent these events; do not duplicate banners.
        completionHandler([.badge])
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                             withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let target = PushTarget(server: info["server"] as? String, deviceID: info["deviceId"] as? String,
                                threadID: info["threadId"] as? String, eventID: info["eventId"] as? String,
                                turnID: info["turnId"] as? String, itemID: info["itemId"] as? String, requestID: info["requestId"] as? String)
        if response.actionIdentifier == UNNotificationDefaultActionIdentifier {
            Task { @MainActor in self.target = target }
        }
        completionHandler()
    }
}
