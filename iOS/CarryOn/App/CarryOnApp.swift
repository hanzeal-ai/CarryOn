import SwiftUI
import CarryOnCore

@main struct CarryOnApp: App {
    @UIApplicationDelegateAdaptor(PushNotifications.self) private var push
    @State private var model = AppModel()
    @State private var iconBadge = AppIconBadge()
    @Environment(\.scenePhase) private var phase
    var body: some Scene {
        WindowGroup {
            RootView().environment(model).tint(Design.blue).preferredColorScheme(.light)
                .task { await model.restoreLogin() }
                .task(id: model.scope + String(model.authenticated) + (push.token ?? "") + String(phase == .active)) {
                    if phase == .active { await push.synchronize(model: model) }
                }
                .task(id: (push.target?.eventID ?? "") + String(model.authenticated)) {
                    if let target = push.target, model.authenticated {
                        await model.openNotification(target)
                        if push.target == target { push.target = nil }
                    }
                }
                .onChange(of: push.registrationError) { _, error in
                    if let error { model.report(APIError(error), operation: "注册 APNs", blocking: false) }
                }
                .onChange(of: model.activityBadgeCount, initial: true) { _, count in
                    iconBadge.update(count, requestAuthorization: false)
                }
                .onChange(of: model.authenticated) { _, authenticated in
                    iconBadge.update(model.activityBadgeCount, requestAuthorization: false)
                }
                .onChange(of: phase) { _, value in
                    model.setForeground(value == .active)
                    iconBadge.update(model.activityBadgeCount, requestAuthorization: false)
                }
        }
    }
}
