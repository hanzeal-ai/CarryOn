import SwiftUI
import CarryOnCore

@main struct NavigationRegressionApp: App {
    @State private var fixture = NavigationFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack { ConversationView(thread: fixture.thread) }
                .environment(fixture.model).task { await fixture.run() }
        }
    }
}
@MainActor @Observable final class NavigationFixture {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("navigation-fixture"), "title": .string("消息导航验证")]))
    func table(_ view: UIView) -> UITableView? {
        if let table = view as? UITableView { return table }
        return view.subviews.lazy.compactMap(table).first
    }
    func pause() async { try? await Task.sleep(for: .seconds(3)) }
    func run() async {
        model.selectedThread = thread
        let rows: [JSONValue] = (1...150).map { .object(["id": .string("message-\($0)"), "type": .string("agentMessage"), "text": .string("消息 \($0) · 用于验证导航定位和当前消息颜色。")]) }
        model.history = .object(["thread":thread.value,"timeline": .array(rows), "status": .object(["state": .string("idle")])])
        model.historyRevision += 1
        await pause()
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first?.windows.first,
              let list = table(window) else { return }
        let before = list.contentOffset.y
        model.activityScrollTarget = "message-20"
        await pause()
        let moved = abs(list.contentOffset.y - before) > 100
        let output = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: output.appendingPathComponent("navigation.png"))
        let result: [String: Any] = ["passed": moved && model.activityScrollTarget == nil, "activityTargetConsumed":model.activityScrollTarget == nil,"scrolledToEarlierMessage":moved]
        try? JSONSerialization.data(withJSONObject: result).write(to: output.appendingPathComponent("navigation-result.json"))
    }
}
