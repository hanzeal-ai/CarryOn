import SwiftUI
import CarryOnCore

// Isolated simulator entry point: real conversation UI, no account or native writes.
@main struct CarryOnApp: App {
    @State private var fixture = InteractionFixture()
    var body: some Scene {
        WindowGroup {
            @Bindable var model = fixture.model
            NavigationStack { ConversationView(thread: fixture.thread) }
                .environment(model)
                .background(ImageLightboxPresenter(image: model.previewImage, isPresented: Binding(
                    get: { model.previewImage != nil }, set: { if !$0 { model.previewImage = nil } }
                )).frame(width: 0, height: 0))
                .task { await fixture.run() }
        }
    }
}
@MainActor @Observable final class InteractionFixture {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("fixture"), "title": .string("图片与历史记录")]))
    var rows: [JSONValue] = []
    func sync() {
        model.history = .object(["timeline": .array(rows), "status": .object(["state": .string("idle")])])
        model.historyRevision += 1
    }
    func pause() async { try? await Task.sleep(for: .seconds(2)) }
    func table(_ view: UIView) -> UITableView? {
        if let value = view as? UITableView { return value }
        return view.subviews.lazy.compactMap(table).first
    }
    func run() async {
        model.selectedThread = thread
        rows = (1...180).map { .object(["id": .string("message-\($0)"), "type": .string("agentMessage"), "text": .string("历史记录 \($0)")]) }
        sync(); await pause()
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first?.windows.first,
              let list = table(window) else { return }
        let before = (0..<list.numberOfSections).reduce(0) { $0 + list.numberOfRows(inSection: $1) }
        list.setContentOffset(CGPoint(x: 0, y: list.contentSize.height - list.bounds.height + 50), animated: false)
        await pause()
        let after = (0..<list.numberOfSections).reduce(0) { $0 + list.numberOfRows(inSection: $1) }
        let image = UIGraphicsImageRenderer(size: CGSize(width: 600, height: 400)).image { context in
            UIColor.systemIndigo.setFill(); context.fill(CGRect(x: 0, y: 0, width: 600, height: 400))
            ("CarryOn 图片预览" as NSString).draw(at: CGPoint(x: 70, y: 160), withAttributes: [.font: UIFont.systemFont(ofSize: 40), .foregroundColor: UIColor.white])
        }
        model.previewImage = image; await pause()
        let opened = window.rootViewController?.presentedViewController is ImageLightboxController
        rows = [.object(["id": .string("picture"), "type": .string("userMessage"), "text": .string("点击缩略图预览"),
            "data": .object(["content": .array([.object(["type": .string("image"), "url": .string("data:image/png;base64," + image.pngData()!.base64EncodedString())])])])]),
            .object(["id": .string("agent"), "type": .string("collabAgentToolCall"), "subagents": .array([.object(["id": .string("child"), "title": .string("子会话图标 · 4pt")])])])]
        sync(); await pause()
        let survived = window.rootViewController?.presentedViewController is ImageLightboxController
        let output = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let screenshot = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? screenshot.pngData()?.write(to: output.appendingPathComponent("preview.png"))
        model.previewImage = nil; await pause()
        let closed = window.rootViewController?.presentedViewController == nil
        let result: [String: Any] = ["rowsBefore": before, "rowsAfter": after, "previewOpened": opened,
            "previewSurvivedMessageReplacement": survived, "previewClosed": closed,
            "passed": after > before && opened && survived && closed]
        try? JSONSerialization.data(withJSONObject: result).write(to: output.appendingPathComponent("result.json"))
        print("INTERACTION_FIXTURE \(output.path)")
    }
}
