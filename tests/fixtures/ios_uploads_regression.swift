import SwiftUI
import UniformTypeIdentifiers
import CarryOnCore

@main struct UploadsRegressionApp: App {
    @State private var fixture = UploadsFixture()
    var body: some Scene {
        WindowGroup {
            ZStack {
                if fixture.creation { NewConversationView() }
                else { NavigationStack { ConversationView(thread: fixture.thread) } }
            }.environment(fixture.model).task { await fixture.run() }
        }
    }
}

@MainActor @Observable final class UploadsFixture {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("11111111-1111-4111-8111-111111111111"), "title": .string("文件附件验收")]))
    var creation = false
    private var started = false
    private var menuDiagnostics: [String] = []
    init() {
        model.restoringLogin = false; model.authenticated = true; model.connected = true; model.foreground = true
        model.historySynchronized = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true),
            "supportsUploads": .bool(true), "supportsDirectCreation": .bool(true),
            "uploadLimits": .object(["chunkBytes": .number(49152), "maxEntries": .number(100), "maxFileBytes": .number(20971520), "maxTotalBytes": .number(52428800)])])
        model.selectedDevice = "uploads-fixture"
        model.devices = [try! Record(.object(["id": .string("uploads-fixture"), "permissions": .array(["view", "send", "create", "files"].map(JSONValue.string))]))]
        model.selectedThread = thread
        model.history = .object(["thread": thread.value, "timeline": .array([]),
            "status": .object(["state": .string("idle")]), "access": .object(["canInteract": .bool(true), "nativeReady": .bool(true)]), "controls": .object([:])])
        model.historyRevision += 1
    }
    private var window: UIWindow? {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows).first(where: \.isKeyWindow)
    }
    private func picker(in controller: UIViewController?) -> UIDocumentPickerViewController? {
        guard let controller else { return nil }
        if let value = controller as? UIDocumentPickerViewController { return value }
        if let value = picker(in: controller.presentedViewController) { return value }
        return controller.children.lazy.compactMap { self.picker(in: $0) }.first
    }
    private func allViews(_ view: UIView) -> [UIView] { [view] + view.subviews.flatMap(allViews) }
    private func menuActions(_ element: UIMenuElement) -> [String] {
        if let menu = element as? UIMenu { return menu.children.flatMap(menuActions) }
        return [element.title]
    }
    private func capture(_ name: String) async {
        try? Data().write(to: URL.documentsDirectory.appendingPathComponent(name + ".capture"))
        for _ in 0..<100 {
            if FileManager.default.fileExists(atPath: URL.documentsDirectory.appendingPathComponent(name + ".captured").path) { return }
            try? await Task.sleep(for: .milliseconds(100))
        }
    }
    private func openUploadMenu(capture: Bool = false) async -> Bool {
        guard let window else { return false }
        let views = allViews(window)
        menuDiagnostics += views.compactMap { view in
            let label = view.accessibilityLabel ?? ""
            return view is UIControl || !label.isEmpty ? "\(type(of: view)): \(label)" : nil
        }
        NotificationCenter.default.post(name: .init("fixture.attachments"), object: true)
        try? await Task.sleep(for: .milliseconds(500))
        func labels(_ object: NSObject, depth: Int = 0) -> [String] {
            guard depth < 16 else { return [] }
            var result = [object.accessibilityLabel].compactMap { $0 }
            let count = object.accessibilityElementCount()
            if count > 0 && count < 1000 {
                for index in 0..<count {
                    if let child = object.accessibilityElement(at: index) as? NSObject { result += labels(child, depth: depth + 1) }
                }
            }
            if let view = object as? UIView { result += view.subviews.flatMap { labels($0, depth: depth + 1) } }
            return result
        }
        let visibleLabels = labels(window)
        menuDiagnostics += visibleLabels
        let menu = visibleLabels.contains("上传文件") && visibleLabels.contains("上传文件夹")
        if capture {
            await self.capture("uploads-menu")
        }
        NotificationCenter.default.post(name: .init("fixture.attachments"), object: false)
        try? await Task.sleep(for: .milliseconds(500))
        return menu
    }
    private func open(_ name: String, kind: UploadKind) async -> UIDocumentPickerViewController? {
        NotificationCenter.default.post(name: .init(name), object: kind.rawValue)
        for _ in 0..<50 {
            if let picker = picker(in: window?.rootViewController), picker.viewIfLoaded?.window != nil,
               !picker.isBeingPresented, !picker.isBeingDismissed { return picker }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return nil
    }
    private func close(_ name: String, picker: UIDocumentPickerViewController?) async -> Bool {
        NotificationCenter.default.post(name: .init(name), object: nil)
        picker?.dismiss(animated: false)
        for _ in 0..<50 {
            try? await Task.sleep(for: .milliseconds(100))
            if self.picker(in: window?.rootViewController)?.viewIfLoaded?.window == nil { return true }
        }
        return false
    }
    func run() async {
        guard !started else { return }; started = true
        try? await Task.sleep(for: .seconds(1))
        var results: [String: Bool] = ["uploadCapability": model.canUpload]
        results["conversationHasUploadMenuEntries"] = await openUploadMenu(capture: true)
        let first = await open("fixture.uploads.conversation", kind: .file)
        results["conversationPresentsFilePicker"] = first != nil && first?.allowsMultipleSelection == true
        results["conversationFilePickerDismisses"] = await close("fixture.uploads.conversation", picker: first)
        let folder = await open("fixture.uploads.conversation", kind: .directory)
        results["conversationPresentsFolderPicker"] = folder != nil && folder?.allowsMultipleSelection == false
        results["conversationFolderPickerDismisses"] = await close("fixture.uploads.conversation", picker: folder)
        let key = model.scope + "\n" + thread.id
        let pending = ConversationUpload(name: "参考资料", kind: .directory, target: .thread(thread.id), entries: [])
        model.draftStore.uploads[key] = [pending]
        results["pendingUploadBlocksSend"] = !model.uploadsReady(key: key, target: .thread(thread.id))
        var completed = pending; completed.uploadID = String(repeating: "a", count: 32)
        model.draftStore.uploads[key] = [completed]
        results["completedUploadCanSendOnlyToOriginalThread"] = model.uploadsReady(key: key, target: .thread(thread.id)) && !model.uploadsReady(key: key, target: .thread("other"))
        model.removeUpload(completed, key: key)
        results["removeUnblocksDraft"] = model.uploadsReady(key: key, target: .thread(thread.id)) && model.draftStore.uploads[key]?.isEmpty == true
        creation = true
        try? await Task.sleep(for: .seconds(1))
        results["creationHasUploadMenuEntries"] = await openUploadMenu()
        let newFile = await open("fixture.uploads.creation", kind: .file)
        results["creationPresentsFilePicker"] = newFile != nil && newFile?.allowsMultipleSelection == true
        results["creationFilePickerDismisses"] = await close("fixture.uploads.creation", picker: newFile)
        let newFolder = await open("fixture.uploads.creation", kind: .directory)
        results["creationPresentsFolderPicker"] = newFolder != nil && newFolder?.allowsMultipleSelection == false
        await capture("uploads-picker")
        if let window {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("uploads.png"))
        }
        results["creationFolderPickerDismisses"] = await close("fixture.uploads.creation", picker: newFolder)
        results["passed"] = results.values.allSatisfy { $0 }
        try? JSONSerialization.data(withJSONObject: results.mapValues { $0 as Any }.merging(["menuDiagnostics": menuDiagnostics]) { _, new in new }).write(to: URL.documentsDirectory.appendingPathComponent("uploads-result.json"))
    }
}
