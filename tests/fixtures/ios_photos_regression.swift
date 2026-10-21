import SwiftUI
import PhotosUI
import CarryOnCore

@main struct PhotosRegressionApp: App {
    @State private var fixture = PhotosFixture()
    var body: some Scene {
        WindowGroup {
            ZStack {
                if fixture.creation { NewConversationView() }
                else { NavigationStack { ConversationView(thread: fixture.thread) } }
            }.environment(fixture.model).task { await fixture.run() }
        }
    }
}

@MainActor @Observable final class PhotosFixture {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("11111111-1111-4111-8111-111111111111"), "title": .string("相册弹窗验收")]))
    var creation = false
    private var started = false
    init() {
        model.restoringLogin = false
        model.authenticated = true
        model.connected = true
        model.foreground = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.selectedDevice = "photos-fixture"
        model.devices = [try! Record(.object(["id": .string("photos-fixture"), "permissions": .array(["view", "send", "create"].map(JSONValue.string))]))]
        model.selectedThread = thread
        model.history = .object(["thread": thread.value, "timeline": .array([]),
            "status": .object(["state": .string("idle")]), "controls": .object([:])])
        model.historyRevision += 1
    }
    private var window: UIWindow? {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows).first(where: \.isKeyWindow)
    }
    private func picker(in controller: UIViewController?) -> PHPickerViewController? {
        guard let controller else { return nil }
        if let value = controller as? PHPickerViewController { return value }
        if let value = picker(in: controller.presentedViewController) { return value }
        return controller.children.lazy.compactMap { self.picker(in: $0) }.first
    }
    private func open(_ name: String) async -> PHPickerViewController? {
        NotificationCenter.default.post(name: .init(name), object: true)
        for _ in 0..<50 {
            if let picker = picker(in: window?.rootViewController), picker.viewIfLoaded?.window != nil,
               !picker.isBeingPresented, !picker.isBeingDismissed { return picker }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return nil
    }
    private func close(_ name: String, picker: PHPickerViewController?) async {
        NotificationCenter.default.post(name: .init(name), object: false)
        picker?.dismiss(animated: false)
        try? await Task.sleep(for: .milliseconds(500))
    }
    func run() async {
        guard !started else { return }; started = true
        try? await Task.sleep(for: .seconds(1))
        var results: [String: Bool] = ["existingConversationCanAttach": model.canCompose]
        let first = await open("fixture.photos.conversation")
        results["existingConversationPresentsSystemPicker"] = first != nil
        results["imageFilterAndThreeSelectionLimit"] = first?.configuration.selectionLimit == 3 && first?.configuration.filter != nil
        await close("fixture.photos.conversation", picker: first)
        let reopened = await open("fixture.photos.conversation")
        results["canReopenAfterDismissal"] = reopened != nil
        await close("fixture.photos.conversation", picker: reopened)
        model.draftImages = ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO1cAAAAASUVORK5CYII="]
        try? await Task.sleep(for: .milliseconds(300))
        results["oneImageDraftLoaded"] = model.draftImages.count == 1
        let limited = await open("fixture.photos.conversation")
        results["remainingSlotsLimit"] = limited?.configuration.selectionLimit == 2
        await close("fixture.photos.conversation", picker: limited)
        creation = true
        try? await Task.sleep(for: .seconds(1))
        let new = await open("fixture.photos.creation")
        results["newConversationPresentsSystemPicker"] = new != nil
        try? Data().write(to: URL.documentsDirectory.appendingPathComponent("photos-picker.capture"))
        try? await Task.sleep(for: .seconds(1))
        if let window {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("photos.png"))
        }
        await close("fixture.photos.creation", picker: new)
        results["passed"] = results.values.allSatisfy { $0 }
        try? JSONSerialization.data(withJSONObject: results).write(to: URL.documentsDirectory.appendingPathComponent("photos-result.json"))
    }
}
