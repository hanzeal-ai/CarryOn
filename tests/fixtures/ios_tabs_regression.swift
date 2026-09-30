import SwiftUI
import CarryOnCore

// No account, remote requests or persistent logs; exercise real root page layout.
@main struct TabsRegressionApp: App {
    @State private var fixture = TabsFixture()
    var body: some Scene {
        WindowGroup { RootView().environment(fixture.model).task { await fixture.run() } }
    }
}

@MainActor @Observable final class TabsFixture: NSObject {
    let model = AppModel()
    private var ticks: [Double] = []
    private var displayLink: CADisplayLink?
    private var started = false
    private var retained: [String: Any] = [:]
    @objc private func tick() { ticks.append(CACurrentMediaTime()) }
    func run() async {
        guard !started else { return }; started = true
        UserDefaults.standard.set(true, forKey: "carryon.projectView")
        UserDefaults.standard.set(false, forKey: "carryon.showInactiveConversations")
        model.restoringLogin = false; model.authenticated = true
        model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "title": .string("导航验证工作区")]))]
        let projects: [JSONValue] = (1...50).map { .object(["id": .string("p\($0)"), "title": .string("项目 \($0)"), "total": .number(50)]) }
        let threads: [JSONValue] = (1...50).map { .object(["id": .string("t\($0)"), "title": .string("会话 \($0)")]) }
        for (path, key, rows) in [("/api/projects", "projects", projects), ("/api/workspace/threads", "threads", threads), ("/api/activity", "threads", threads)] {
            let suffix = "?limit=50&offset=0&search=&filter=all&availableOnly=true" + (path == "/api/activity" ? "&includeRead=true" : "")
            let value: JSONValue = .object([key: .array(rows), "total": .number(50), "nextOffset": .number(50)])
            model.displayCache.store(value, key: model.scope + "\n" + path + suffix, bytes: 10000)
        }
        try? await Task.sleep(for: .seconds(2))
        let observer = NotificationCenter.default.addObserver(forName: Notification.Name("fixture.state"), object: nil, queue: .main) { [weak self] note in
            MainActor.assumeIsolated { self?.retained = note.object as? [String: Any] ?? [:] }
        }
        defer { NotificationCenter.default.removeObserver(observer) }
        NotificationCenter.default.post(name: Notification.Name("fixture.seed"), object: nil)
        try? await Task.sleep(for: .milliseconds(350))
        UserDefaults.standard.set(false, forKey: "carryon.projectView")
        try? await Task.sleep(for: .milliseconds(350))
        UserDefaults.standard.set(true, forKey: "carryon.projectView")
        try? await Task.sleep(for: .milliseconds(350))
        displayLink = CADisplayLink(target: self, selector: #selector(tick))
        displayLink?.add(to: .main, forMode: .common)
        var delays: [Double] = []
        for index in 0..<18 {
            let start = CACurrentMediaTime()
            NotificationCenter.default.post(name: Notification.Name("fixture.tab"), object: (index + 1) % 3)
            try? await Task.sleep(for: .milliseconds(250))
            delays.append(CACurrentMediaTime() - start)
        }
        displayLink?.invalidate(); displayLink = nil
        let gap = zip(ticks, ticks.dropFirst()).map { $1 - $0 }.max() ?? 1
        let delay = delays.max() ?? 1
        NotificationCenter.default.post(name: Notification.Name("fixture.inspect"), object: nil)
        let retainedState = retained["search"] as? String == "项目" && retained["records"] as? Int == 50 && !(retained["scroll"] as? String ?? "").isEmpty
        let filtersIsolated = retained["projectFilter"] as? String == "all" && retained["threadFilter"] as? String == "running"
        let markdown = await MessageMarkdownParser.shared.prepare(.object(["type": .string("agentMessage"), "text": .string("**最新消息**\n\n- 已完成")]))
        let markdownReady = markdown?.content.renderPlainText().contains("最新消息") == true
        var result: [String: Any] = ["passed": ticks.count > 30 && gap < 0.5 && delay < 0.75 && retainedState && markdownReady && filtersIsolated,
            "retainedListState": retainedState, "viewModeFiltersIsolated": filtersIsolated, "retainedStateValues": retained, "preparedMarkdown": markdownReady,
            "switches": delays.count, "frames": ticks.count, "maxFrameGapSeconds": gap, "maxSwitchDelaySeconds": delay]
        if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
            func scrollOffsets(_ view: UIView) -> [CGFloat] {
                let own = (view as? UIScrollView).map { $0.bounds.height > 300 && $0.contentSize.height > $0.bounds.height + 100 ? [$0.contentOffset.y] : [] } ?? []
                return own + view.subviews.flatMap(scrollOffsets)
            }
            let offset = scrollOffsets(window).max() ?? 0
            result["listScrollOffset"] = offset
            result["passed"] = (result["passed"] as? Bool == true) && offset > 50
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("tabs.png"))
        }
        model.selectedDevice = "fixture-other"
        try? await Task.sleep(for: .milliseconds(350))
        NotificationCenter.default.post(name: Notification.Name("fixture.inspect"), object: nil)
        let isolated = retained["search"] as? String == "" && retained["records"] as? Int == 0
        result["workspaceStateIsolated"] = isolated
        result["passed"] = (result["passed"] as? Bool == true) && isolated
        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("tabs-result.json"))
    }
}
