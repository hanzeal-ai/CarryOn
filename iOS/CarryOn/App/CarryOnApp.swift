import SwiftUI

@main struct CarryOnApp: App {
    @State private var model = AppModel()
    @State private var iconBadge = AppIconBadge()
    @Environment(\.scenePhase) private var phase
    var body: some Scene {
        WindowGroup {
            RootView().environment(model).tint(Design.blue).preferredColorScheme(.light)
                .onChange(of: model.activityBadgeCount, initial: true) { _, count in
                    iconBadge.update(count, requestAuthorization: model.authenticated && phase == .active)
                }
                .onChange(of: model.authenticated) { _, authenticated in
                    iconBadge.update(model.activityBadgeCount, requestAuthorization: authenticated && phase == .active)
                }
                .onChange(of: phase) { _, value in
                    model.setForeground(value == .active)
                    iconBadge.update(model.activityBadgeCount, requestAuthorization: model.authenticated && value == .active)
                }
        }
    }
}
