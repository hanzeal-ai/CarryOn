import SwiftUI
import CarryOnCore

@main struct SearchRegressionApp: App {
    @State private var fixture = SearchFixture()
    var body: some Scene { WindowGroup {
        NavigationStack { if let thread = fixture.model.selectedThread { ConversationView(thread: thread) } else { Text("内容搜索回归") } }.sheet(isPresented: $fixture.show) { ConversationSearchView() }
            .environment(fixture.model)
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.snapshot"))) { note in
                if let value = note.object as? [String: Any] { fixture.snapshot = value }
            }.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.live"))) { _ in
                fixture.liveBeforeHTTP = true
                fixture.model.history = .object(["thread": .object(["id": .string("t1")]), "timeline": .array([.object(["id": .string("new-live"), "type": .string("agentMessage"), "text": .string("LIVE WITHOUT HIT")])])])
                fixture.model.historySynchronized = true; fixture.model.historyRevision += 1
            }.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.rendered"))) { note in fixture.rendered = note.object as? [String: Any] ?? [:] }.task { await fixture.run() }
    } }
}
private final class SearchTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock(); var writes = 0; var cursors: [String] = []
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            if envelope["method"] as? String == "POST" { writes += 1 }
            let target = envelope["path"] as? String ?? ""
            let url = URLComponents(string: "https://fixture.invalid" + target)!
            let term = url.queryItems?.first { $0.name == "search" }?.value ?? ""
            let cursor = url.queryItems?.first { $0.name == "cursor" }?.value
            if let cursor { cursors.append(cursor) }
            if url.path == "/api/search" {
                return ["threads": [["id": cursor == nil ? "t1" : "t2", "title": "搜索测试", "cwd": "/workspace", "snippet": term + " match"]], "nextCursor": cursor == nil ? "native|opaque" : NSNull()]
            }
            if url.path == "/api/threads/t1/search-anchor" { return ["threadId": "t1", "itemId": "hit", "turnId": "turn", "historyLimit": 3] }
            if url.path == "/api/threads/t1/history" {
                let hit: [String: Any] = ["id": "native-hit", "nativeId": "hit", "turnId": "turn", "type": "agentMessage", "status": "completed", "text": "MATCHED MESSAGE"]
                let tail: [[String: Any]] = (0..<140).map { ["id": "later-\($0)", "turnId": "later-turn", "type": "agentMessage", "status": "completed", "text": "later message \($0)"] }
                return ["thread": ["id": "t1"], "historyRevision": "search-fixture", "runtime": ["type": "idle"], "status": ["state": "idle"], "metadata": [:], "access": ["canInteract": false, "nativeReady": false], "controls": [:], "timeline": [hit] + tail]
            }
            if url.path == "/api/threads/t1/search" {
                return ["threadId": "t1", "occurrences": [["itemId": "hit", "turnId": "turn", "turnCursor": "native-turn", "snippet": "🧭 fixture 命中", "snippetMatchRange": ["start": 3, "end": 10]]], "nextCursor": NSNull()]
            }
            return [:]
        }
        func counts() -> (Int, [String]) { lock.lock(); defer { lock.unlock() }; return (writes, cursors) }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; bytes.append(buffer, count: n) }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let data = try! JSONSerialization.data(withJSONObject: Self.store.respond(envelope))
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        let deliver: @Sendable () -> Void = { [self] in
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        }
        if (envelope["path"] as? String ?? "").contains("/history") {
            DispatchQueue.main.async { NotificationCenter.default.post(name: Notification.Name("fixture.search.live"), object: nil) }
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.2, execute: deliver)
        }
        else if (envelope["path"] as? String ?? "").contains("search=late") { DispatchQueue.global().asyncAfter(deadline: .now() + 1, execute: deliver) }
        else { deliver() }
    }
    override func stopLoading() {}
}
@MainActor @Observable private final class SearchFixture {
    let model = AppModel(); var show = false; var started = false; var liveBeforeHTTP = false
    @ObservationIgnored var rendered: [String: Any] = [:]
    @ObservationIgnored var snapshot: [String: Any] = [:]
    func pause(_ ms: Int = 650) async { try? await Task.sleep(for: .milliseconds(ms)) }
    func post(_ action: String, _ value: String? = nil) { NotificationCenter.default.post(name: Notification.Name("fixture.search." + action), object: value) }
    func inspect() -> [JSONValue] { post("inspect"); return snapshot["rows"] as? [JSONValue] ?? [] }
    func marker(_ view: UIView) -> UIView? {
        if view.accessibilityIdentifier == "conversation-message-native-hit" { return view }
        for child in view.subviews { if let found = marker(child) { return found } }
        return nil
    }
    func table(_ view: UIView) -> UITableView? {
        if let table = view as? UITableView { return table }
        return view.subviews.lazy.compactMap { self.table($0) }.first
    }
    func visibleHit() -> Bool {
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow), let hit = marker(window) else { return false }
        var ancestor: UIView? = hit
        while let view = ancestor { if let table = view as? UITableView { let rect = hit.convert(hit.bounds, to: window); return rect.intersects(table.convert(table.bounds, to: window)) && rect.intersects(window.bounds) }; ancestor = view.superview }
        return false
    }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [SearchTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://search-fixture.invalid/"), configuration: config))
        model.addressText = "https://search-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array([.string("view")])]))]
        model.authenticated = true; model.connected = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(false), "supportsFullTextSearch": .bool(true)])
        show = true; await pause(); post("query", "fixture"); await pause()
        let initial = inspect().count == 1
        post("more"); await pause(); let paged = inspect().count == 2 && SearchTransport.store.counts().1 == ["native|opaque"]
        post("select"); await pause(); let occurrences = inspect().first?["snippet"].text == "🧭 fixture 命中"
        let highlighted = snapshot["highlighted"] as? Bool == true
        if let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("search.png"))
        }
        show = false; await pause(); show = true; await pause()
        post("query", "late"); await pause(350); post("query", "current"); await pause(1500)
        let queryStable = inspect().first?["snippet"].text == "current match"
        post("query", "late"); await pause(350)
        model.devices.append(try! Record(.object(["id": .string("other"), "online": .bool(true), "permissions": .array([.string("view")])])))
        model.selectedDevice = "other"; await pause(1500)
        let scopeIsolated = inspect().isEmpty
        model.devices = [try! Record(.object(["id": .string("other"), "online": .bool(true), "permissions": .array([])]))]
        await pause(); let revoked = !show
        model.devices = [try! Record(.object(["id": .string("other"), "online": .bool(true), "permissions": .array([.string("view")])]))]
        let record = try! Record(.object(["id": .string("t1"), "title": .string("搜索测试")]))
        let occurrence: JSONValue = .object(["itemId": .string("hit"), "turnId": .string("turn"), "turnCursor": .string("native-turn")])
        var wrongRefused = false
        do { try await model.openSearchOccurrence(record, occurrence: .object(["itemId": .string("wrong"), "turnId": .string("turn"), "turnCursor": .string("native-turn")])) } catch { wrongRefused = model.selectedThread == nil }
        var anchorError = ""
        do { try await model.openSearchOccurrence(record, occurrence: occurrence) } catch { anchorError = error.localizedDescription }
        post("offsetburst")
        let anchorStart = ContinuousClock.now
        while !visibleHit(), anchorStart.duration(to: .now) < .seconds(3) { await pause(50) }
        let initialAnchorVisible = visibleHit()
        let anchorLatency = anchorStart.duration(to: .now)
        let resized = model.history["timeline"].array.map { row in row["id"].text == "native-hit" ? row.setting("text", .string(Array(repeating: "MATCHED MESSAGE AFTER LAYOUT", count: 18).joined(separator: "\n"))) : row }
        model.history = model.history.setting("timeline", .array(resized)); model.historyRevision += 1
        await pause(1500)
        let nativeAnchored = model.selectedThread?.id == "t1" && model.readingState(for: "t1").anchorID == "native-hit" && visibleHit()
        let noWrites = SearchTransport.store.counts().0 == 0
        post("render")
        var diagnostic: [String: Any] = ["error": anchorError, "selected": model.selectedThread?.id ?? "", "anchor": model.readingState(for: "t1").anchorID ?? "", "historyNull": model.history == .null, "timelineCount": model.history["timeline"].array.count, "connected": model.connected, "authenticated": model.authenticated]
        diagnostic["initialAnchorVisible"] = initialAnchorVisible
        diagnostic["anchorLatency"] = String(describing: anchorLatency)
        diagnostic["rendered"] = rendered
        if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).flatMap(\.windows).first(where: \.isKeyWindow) {
            diagnostic["windowBounds"] = NSCoder.string(for: window.bounds)
            if let table = table(window) {
                diagnostic["offset"] = table.contentOffset.y
                diagnostic["contentHeight"] = table.contentSize.height
                diagnostic["tableBounds"] = NSCoder.string(for: table.bounds)
                diagnostic["visibleRows"] = table.indexPathsForVisibleRows?.map { "\($0.section):\($0.row)" } ?? []
                diagnostic["rows"] = (0..<table.numberOfSections).map { table.numberOfRows(inSection: $0) }
            }
            if let hit = marker(window) { diagnostic["hitFrame"] = NSCoder.string(for: hit.convert(hit.bounds, to: window)); diagnostic["hitBounds"] = NSCoder.string(for: hit.bounds) }
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("search-anchor.png"))
        }
        try? JSONSerialization.data(withJSONObject: diagnostic).write(to: URL.documentsDirectory.appendingPathComponent("search-diagnostic.json"))
        let result: [String: Bool] = ["passed": initial && paged && occurrences && highlighted && queryStable && scopeIsolated && revoked && noWrites && wrongRefused && nativeAnchored && liveBeforeHTTP && initialAnchorVisible, "lateSizeChangeAndOffsetBurst": initialAnchorVisible && nativeAnchored, "liveWithoutHitThenHTTP": liveBeforeHTTP && nativeAnchored, "viewOnlySearch": initial, "wrongAnchorRefused": wrongRefused, "nativeAnchorVisible": nativeAnchored, "nativeCursorPreserved": paged, "occurrencesShown": occurrences, "utf16Highlight": highlighted, "queryStable": queryStable, "scopeIsolated": scopeIsolated, "permissionRevokedCloses": revoked, "noWrites": noWrites]
        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("search-result.json"))
    }
}
