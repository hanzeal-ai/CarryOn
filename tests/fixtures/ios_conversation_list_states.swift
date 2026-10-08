import SwiftUI
import CarryOnCore

@main struct ListStatesApp: App {
    @State private var fixture = ListStatesFixture()
    var body: some Scene { WindowGroup {
        NavigationStack {
            if fixture.mounted { ConversationView(thread: fixture.thread) }
            else { Text("已关闭") }
        }.environment(fixture.model)
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.headerBody"))) { fixture.headerBody = $0.object as? String ?? "" }
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.questionRender"))) { fixture.questionRenders.append($0.object as? [String: Bool] ?? [:]) }
        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.navigationReceipt"))) { fixture.navigationReceipt = $0.object as? [String: String] ?? [:] }
        .task { await fixture.run() }
    } }
}
struct FixtureHeaderMarker: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView { let view = UIView(); view.accessibilityIdentifier = "fixture-history-header"; return view }
    func updateUIView(_ view: UIView, context: Context) {}
}
struct FixtureQuestionMarker: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView { let view = UIView(); view.accessibilityIdentifier = "fixture-async-question"; return view }
    func updateUIView(_ view: UIView, context: Context) {}
}
@MainActor @Observable final class ListStatesFixture {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("states"), "title": .string("列表状态验证")]))
    var mounted = true
    var started = false
    @ObservationIgnored var navigationReceipt: [String: String] = [:]
    @ObservationIgnored var questionRenders: [[String: Bool]] = []
    @ObservationIgnored var questionGeometry: [[String: Any]] = []
    @ObservationIgnored var headerBody = ""
    @ObservationIgnored var checks: [String: Bool] = [:]
    @ObservationIgnored var savedIDs: [String: String] = [:]
    @ObservationIgnored var readingMetrics: [String: CGFloat] = [:]
    @ObservationIgnored var heights: [String: CGFloat] = [:]
    var window: UIWindow? { UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows).first(where: \.isKeyWindow) }
    func find(_ root: UIView, _ id: String) -> UIView? {
        if root.accessibilityIdentifier == id { return root }
        for child in root.subviews { if let view = find(child, id) { return view } }; return nil
    }
    func table(_ root: UIView) -> UITableView? {
        if let view = root as? UITableView { return view }
        for child in root.subviews { if let view = table(child) { return view } }; return nil
    }
    func glyph(in marker: UIView) -> (String, CGFloat)? {
        var root: UIView = marker
        while !(root is UITableViewCell), let parent = root.superview { root = parent }
        func texts(_ view: UIView) -> [UITextView] { if let text = view as? UITextView { return text.isEditable ? [] : [text] }; return view.subviews.flatMap(texts) }
        guard let window, let view = texts(root).first(where: { !$0.text.isEmpty }),
              let end = view.position(from: view.beginningOfDocument, offset: 1),
              let range = view.textRange(from: view.beginningOfDocument, to: end) else { return nil }
        return (view.text, view.convert(view.firstRect(for: range), to: window).minY)
    }
    func questionVisible() -> Bool {
        guard let window, let table = table(window) else { return false }
        let viewport = table.convert(table.bounds, to: window)
        return table.visibleCells.filter { !$0.isHidden }.contains { cell in
            guard let marker = find(cell, "fixture-async-question"), marker.bounds.height > 0 else { return false }
            return marker.convert(marker.bounds, to: window).intersects(viewport)
        }
    }
    func wait() async { try? await Task.sleep(for: .milliseconds(700)) }
    func capture(_ name: String, expected: String) async {
        await wait()
        guard let window, let table = table(window) else { checks[name] = false; return }
        let index = IndexPath(row: table.numberOfRows(inSection: 0) - 1, section: 0)
        for _ in 0..<3 { table.scrollToRow(at: index, at: .bottom, animated: false); await wait() }
        table.layoutIfNeeded()
        let marker = find(window, "fixture-history-header")
        let height: CGFloat = expected == "normal" && table.numberOfRows(inSection: 0) == 8 ? 0 : table.rectForRow(at: index).height
        heights[name] = height
        checks[name] = expected == "normal" ? (table.numberOfRows(inSection: 0) == 8) : headerBody == expected && marker != nil && height > 0
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("liststates-" + name + ".png"))
    }
    func history(_ syncing: Bool = false, more: Bool = false, limit: Int = 40) -> JSONValue {
        .object(["thread": thread.value, "status": .object(["state": .string("idle")]), "syncing": .bool(syncing), "controls": .object(["supportedOperations": .array([.string("side-create")])]), "historyWindow": .object(["limit": .number(Double(limit)), "hasMore": .bool(more)]), "timeline": .array((0..<8).map { .object(["id": .string("row-\($0)"), "type": .string("agentMessage"), "text": .string("保留正文 \($0)。" + String(repeating: "这段长正文用于检查关闭后仍恢复同一阅读位置。", count: 22)), "status": .string("completed")]) })])
    }
    func run() async {
        guard !started else { return }; started = true
        model.addressText = "https://states-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array([.string("view"), .string("create")])]))]
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.authenticated = true; model.connected = false; model.foreground = true
        model.selectedThread = thread; model.history = .null
        await capture("loading", expected: "loading")
        model.historyFailure = "受控加载失败"
        await capture("failed", expected: "failed")
        model.retryHistory()
        await capture("retry", expected: "loading")
        model.connected = true
        model.history = history(); model.historySynchronized = true; model.historyRevision += 1
        await capture("normal", expected: "normal")
        let original = model.history["timeline"]
        model.history = history(true)
        await capture("syncing", expected: "syncing")
        checks["syncingLeavesMessagesUnchanged"] = original == model.history["timeline"]
        model.history = history()
        await capture("synced", expected: "normal")
        model.historyFailure = "保留正文的同步错误"
        await capture("retainedFailure", expected: "retainedFailure")
        checks["errorLeavesMessagesUnchanged"] = original == model.history["timeline"]
        model.historyFailure = nil
        await capture("retainedRetry", expected: "normal")
        checks["headerHeightsUpdate"] = (heights["loading"] ?? 0) > (heights["normal"] ?? 0) && (heights["failed"] ?? 0) > (heights["normal"] ?? 0) && (heights["syncing"] ?? 0) > (heights["synced"] ?? 0) && (heights["retainedFailure"] ?? 0) > (heights["retainedRetry"] ?? 0)
        let before = window.flatMap { table($0) }
        let anchor = window.flatMap { find($0, "conversation-message-row-0") }
        let oldGlyph = anchor.flatMap { glyph(in: $0) }
        let anchorY = anchor.flatMap { view in window.map { view.convert(view.bounds, to: $0).minY } }
        let savedOffset = before?.contentOffset.y
        savedIDs["before-\(checks.count)"] = model.readingState(for: thread.id).visiblePosition?.id ?? "nil"
        readingMetrics["beforeOffset"] = savedOffset; readingMetrics["beforeY"] = anchorY; readingMetrics["storedOffset"] = model.readingState(for: thread.id).offset
        mounted = false; await wait()
        checks["closeRemovesTable"] = window.flatMap { table($0) } == nil
        mounted = true; await wait()
        savedIDs["after-\(checks.count)"] = model.readingState(for: thread.id).visiblePosition?.id ?? "nil"
        checks["reopenCreatesCurrentTable"] = window.flatMap { table($0) }.map { $0 !== before } == true && model.selectedThread?.id == thread.id
        if let window, let reopened = table(window), savedOffset != nil, let anchorY, let marker = find(window, "conversation-message-row-0") {
            readingMetrics["beforeGlyphY"] = oldGlyph?.1; readingMetrics["afterGlyphY"] = glyph(in: marker)?.1
            readingMetrics["afterOffset"] = reopened.contentOffset.y; readingMetrics["afterY"] = marker.convert(marker.bounds, to: window).minY
            checks["reopenPreservesReadingPosition"] = abs(marker.convert(marker.bounds, to: window).minY - anchorY) < 1 && oldGlyph.map { old in glyph(in: marker).map { $0.0 == old.0 && abs($0.1 - old.1) < 1 } == true } == true
        } else { checks["reopenPreservesReadingPosition"] = false }
        model.activityScrollTarget = "row-7"; await wait(); await wait()
        checks["navigationTargetConsumedBeforeReading"] = model.activityScrollTarget == nil && window.flatMap { find($0, "conversation-message-row-7") } != nil
        NotificationCenter.default.post(name: .init("fixture.userReadingIntent"), object: nil)
        if let window, let table = table(window) {
            for _ in 0..<3 { table.scrollToRow(at: IndexPath(row: table.numberOfRows(inSection: 0) - 1, section: 0), at: .bottom, animated: false); await wait() }
        }
        do {
        let before = window.flatMap { table($0) }
        let anchor = window.flatMap { find($0, "conversation-message-row-0") }
        let oldGlyph = anchor.flatMap { glyph(in: $0) }
        let anchorY = anchor.flatMap { view in window.map { view.convert(view.bounds, to: $0).minY } }
        let savedOffset = before?.contentOffset.y
        savedIDs["before-\(checks.count)"] = model.readingState(for: thread.id).visiblePosition?.id ?? "nil"
        readingMetrics["navigation-beforeOffset"] = savedOffset; readingMetrics["navigation-beforeY"] = anchorY; readingMetrics["navigation-storedOffset"] = model.readingState(for: thread.id).offset
        mounted = false; await wait()
        checks["navigationThenReadingCloseRemovesTable"] = window.flatMap { table($0) } == nil
        mounted = true; await wait()
        savedIDs["after-\(checks.count)"] = model.readingState(for: thread.id).visiblePosition?.id ?? "nil"
        checks["navigationThenReadingReopenCreatesTable"] = window.flatMap { table($0) }.map { $0 !== before } == true && model.selectedThread?.id == thread.id
        if let window, let reopened = table(window), savedOffset != nil, let anchorY, let marker = find(window, "conversation-message-row-0") {
            readingMetrics["navigation-beforeGlyphY"] = oldGlyph?.1; readingMetrics["navigation-afterGlyphY"] = glyph(in: marker)?.1
            readingMetrics["navigation-afterOffset"] = reopened.contentOffset.y; readingMetrics["navigation-afterY"] = marker.convert(marker.bounds, to: window).minY
            checks["navigationThenReadingReopenPreservesGlyph"] = abs(marker.convert(marker.bounds, to: window).minY - anchorY) < 1 && oldGlyph.map { old in glyph(in: marker).map { $0.0 == old.0 && abs($0.1 - old.1) < 1 } == true } == true
        } else { checks["navigationThenReadingReopenPreservesGlyph"] = false }
        }
        model.connected = true; model.history = history(more: true); model.historyRevision += 1
        await wait()
        if let window, let table = table(window) {
            table.setContentOffset(CGPoint(x: 0, y: max(0, table.contentSize.height - table.bounds.height)), animated: false)
        }
        await wait(); checks["visibleBoundaryRequestsNativeWindow"] = model.historyLimit == 80
        model.history = history(limit: 80); model.historyRevision += 1; await wait()
        checks["expandedNativeWindowSettles"] = model.historyFailure == nil && model.historyLimit == 80
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array([.string("view")])]))]
        var withQuestion = model.history["timeline"].array
        withQuestion[withQuestion.count - 1] = withQuestion.last!.setting("asyncQuestions", .array([.object(["id": .string("question"), "title": .string("保留当前实现？"), "options": .array([.string("是"), .string("否")])])]))
        model.history = model.history.setting("timeline", .array(withQuestion)).setting("access", .object(["canInteract": .bool(true)])).setting("controls", .object(["supportedOperations": .array([])])); model.historyRevision += 1
        await wait()
        if let window, let table = table(window) { table.setContentOffset(.zero, animated: false) }
        await wait()
        if let window, let table = table(window) { table.scrollToRow(at: IndexPath(row: 0, section: 0), at: .top, animated: false) }; await wait()
        checks["questionsVisibleWithoutEditOrSidePermission"] = questionVisible() && !model.canWrite(.create) && !model.canInteract(.edit)
        model.history = model.history.setting("access", .object(["canInteract": .bool(false)]))
        await wait()
        if let window, let marker = find(window, "fixture-async-question") {
            var ancestors: [[String: Any]] = []; var next: UIView? = marker
            while let view = next { ancestors.append(["type": String(describing: type(of: view)), "hidden": view.isHidden, "alpha": view.alpha, "rect": NSCoder.string(for: view.convert(view.bounds, to: window))]); next = view.superview }
            questionGeometry = ancestors
        }
        checks["readOnlyHidesUnchangedQuestion"] = !questionVisible() && questionRenders.last?["readOnly"] == true
        model.history = model.history.setting("access", .object(["canInteract": .bool(true)]))
        await wait(); if let window, let table = table(window) { table.scrollToRow(at: IndexPath(row: 0, section: 0), at: .top, animated: false) }; await wait(); checks["writePresentationRestoresUnchangedQuestion"] = questionVisible() && model.history["timeline"].array == withQuestion
        if let window, let table = table(window) { for _ in 0..<3 { table.scrollToRow(at: IndexPath(row: table.numberOfRows(inSection: 0) - 1, section: 0), at: .bottom, animated: false); await wait() } }
        let removedID = model.readingState(for: thread.id).visiblePosition?.id
        savedIDs["deletedActualID"] = removedID ?? "nil"
        checks["deletedPositionWasActuallySaved"] = removedID == "row-0"
        mounted = false; await wait()
        model.history = model.history.setting("timeline", .array(model.history["timeline"].array.filter { $0.stableID != removedID }))
        model.historySynchronized = true; model.historyRevision += 1
        mounted = true; await wait(); await wait()
        NotificationCenter.default.post(name: .init("fixture.navigationInspect"), object: nil)
        checks["deletedPositionDoesNotLeavePendingRestore"] = removedID != nil && navigationReceipt["restoreTarget"] != removedID && model.readingState(for: thread.id).visiblePosition?.id != removedID
        checks["deletedPositionReturnsToLatest"] = window.flatMap { table($0) }.map { abs($0.contentOffset.y) <= 20 } == true && window.flatMap { find($0, "conversation-message-row-7") } != nil
        model.activityScrollTarget = "late-row"; await wait()
        NotificationCenter.default.post(name: .init("fixture.navigationInspect"), object: nil)
        checks["lateActivityTargetIsNotInvalidated"] = model.activityScrollTarget == "late-row" && navigationReceipt["pendingTarget"] == "late-row"
        model.history = model.history.setting("timeline", .array(model.history["timeline"].array + [.object(["id": .string("late-row"), "type": .string("agentMessage"), "text": .string("迟到的活动目标"), "status": .string("completed")])]))
        model.historyRevision += 1; await wait(); await wait()
        checks["lateActivityTargetIsResolvedWhenPublished"] = model.activityScrollTarget == nil && window.flatMap { find($0, "conversation-message-late-row") } != nil
        if let window {
            let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent("liststates.png"))
        }
        let result: [String: Any] = ["passed": checks.count == 28 && checks.values.allSatisfy { $0 }, "checks": checks, "heights": heights, "readingMetrics": readingMetrics, "questionRenders": questionRenders, "questionGeometry": questionGeometry, "savedIDs": savedIDs]
        try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: URL.documentsDirectory.appendingPathComponent("liststates-result.json"))
    }
}
