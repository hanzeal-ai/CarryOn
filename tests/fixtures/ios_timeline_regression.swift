import SwiftUI
import CarryOnCore

// Simulator-only entry point. Copy over CarryOnApp.swift in an isolated iOS checkout.
// Uses the real ConversationView with local snapshots; no login or message API is invoked.
@main struct CarryOnApp: App {
    @State private var fixture = TimelineFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack { ConversationView(thread: fixture.thread) }.environment(fixture.model)
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.projection"))) { fixture.recordProjection($0) }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.timing"))) { fixture.recordTiming($0) }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.beforeTransaction"))) { _ in fixture.scrollBeforeTransaction() }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.queueCount"))) { fixture.visibleQueueCount = $0.object as? Int ?? -1 }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.readingAnchor"))) { fixture.readingAnchors.append($0.object as? [String: Any] ?? [:]) }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.entryRender"))) { fixture.recordRender($0) }
                .task { await fixture.run() }
        }
    }
}
@MainActor @Observable final class TimelineFixture: NSObject {
    let performanceOnly = false
    let boundaryOnly = false
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("fixture"), "title": .string("时间线回归")]))
    var rows: [JSONValue] = []
    var readingAnchors: [[String: Any]] = []
    var samples: [[String: Any]] = []
    var projections: [[String: Any]] = []
    @ObservationIgnored var timings: [[String: Any]] = []
    @ObservationIgnored var scrollDuringProjection = false
    @ObservationIgnored var concurrentAnchor: (String, CGFloat)?
    @ObservationIgnored var visibleQueueCount = 0
    @ObservationIgnored var bodyRenders: [String: Int] = [:]
    @ObservationIgnored weak var sampledTable: UITableView?
    var timer: CADisplayLink?
    var start = 0.0
    func entry(_ id: String, _ type: String, _ text: String) -> JSONValue {
        .object(["id": .string(id), "type": .string(type), "title": .string(text), "text": .string(text), "status": .string("completed")])
    }
    func sync() {
        model.history = .object(["thread": .object(["id": .string("fixture")]), "timeline": .array(rows), "status": .object(["state": .string("idle")]), "source": .string("desktop-snapshot"), "controls": .object(["supportedOperations": .array([.string("side-create")])]), "access": .object(["canInteract": .bool(true), "nativeReady": .bool(true)])])
        model.historyRevision += 1
    }
    func run() async {
        if boundaryOnly || performanceOnly {
            model.selectedDevice = "fixture"; model.addressText = "https://timeline-fixture.invalid/"
            model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "send", "edit", "create"].map(JSONValue.string))]))]
            model.authenticated = true; model.connected = true; model.historySynchronized = true
            model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        }
        model.selectedThread = thread
        rows = [entry("turn1", "turn", "第 1 轮"), entry("u1", "userMessage", "检查会话更新时的气泡高度"), entry("a1", "agentMessage", "这是一段已有回复。\n\n发送新消息时，这段内容应保持可见，不能先压缩再展开。\n\n- 保留内容\n- 保留布局\n- 连续更新"), entry("turn2", "turn", "第 2 轮"), entry("u2", "userMessage", "继续检查"), entry("a2", "agentMessage", "已有回复第二段。\n\n发送中的状态变化不应导致已有气泡重复播放高度动画。")]
        rows.insert(contentsOf: (0..<1000).map { entry("earlier-\($0)", "agentMessage", "较早的回答 \($0)。长历史更新时保持当前阅读区域。") }, at: 0)
        sync()
        try? await Task.sleep(for: .seconds(5))
        var keyboardStarted = !(boundaryOnly || performanceOnly)
        if boundaryOnly || performanceOnly {
            keyboardStarted = keyWindow.flatMap { editableText(in: $0) }?.becomeFirstResponder() == true
            try? await Task.sleep(for: .milliseconds(700))
        }
        start = CACurrentMediaTime()
        timer = CADisplayLink(target: self, selector: #selector(sample)); timer?.add(to: .main, forMode: .common)
        try? await Task.sleep(for: .milliseconds(400))
        let beforeQueueUpdate = projections.count
        let beforeQueueTransactions = timings.filter { $0["stage"] as? String == "tableTransaction" }.count
        model.history = model.history.setting("queue", .object(["fingerprint": .string("fixture-queue"), "messages": .array([.object(["id": .string("fixture-queued"), "text": .string("之后检查队列"), "context": .array([])])])]))
        model.historyRevision += 1
        try? await Task.sleep(for: .milliseconds(300))
        let queueUpdatePreserved = projections.count == beforeQueueUpdate && timings.filter { $0["stage"] as? String == "tableTransaction" }.count == beforeQueueTransactions
        let queueCountUpdated = visibleQueueCount == 1
        if !performanceOnly, let window = keyWindow {
            let image = UIGraphicsImageRenderer(size: window.bounds.size).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            try? image.pngData()?.write(to: root.appendingPathComponent("timeline-queue.png"))
        }
        try? await Task.sleep(for: .milliseconds(300))
        model.outgoing["send"] = .object(["id": .string("send"), "scope": .string(model.scope), "threadId": .string("fixture"), "prompt": .string("hello"), "state": .string("sending")])
        try? await Task.sleep(for: .seconds(1))
        rows += [entry("turn3", "turn", "第 3 轮"), entry("u3", "userMessage", "hello")]; sync()
        try? await Task.sleep(for: .milliseconds(250))
        model.outgoing.removeAll()
        try? await Task.sleep(for: .seconds(1))
        rows.append(entry("a3", "agentMessage", "开始回复")); sync()
        for n in 1...5 {
            try? await Task.sleep(for: .milliseconds(200))
            rows[rows.count - 1] = entry("a3", "agentMessage", (0..<(n * (boundaryOnly ? 8 : 1))).map { "回复段落 \($0)：持续追加，旧气泡保持稳定。\n\n" }.joined()); sync()
        }
        try? await Task.sleep(for: .seconds(1))
        var nearBottomPreserved = !boundaryOnly
        var nearBottomDeltas: [CGFloat] = []
        var nearBottomCellGeometry: [[String: CGFloat]] = []
        var latestVisible = !boundaryOnly
        var returnToLatestPassed = !boundaryOnly
        var concurrentScrollPreserved = !boundaryOnly
        if boundaryOnly, let window = keyWindow, let t = table(in: window) {
            latestVisible = abs(t.contentOffset.y) < 1 && t.visibleCells.contains { messageID($0) == "a3" }
            nearBottomPreserved = true
            for offset in [5.0, 20.0] {
                t.setContentOffset(CGPoint(x: 0, y: offset), animated: false)
                try? await Task.sleep(for: .milliseconds(300))
                if let cell = t.visibleCells.first(where: { messageID($0) != nil && messageID($0) != "carryon:status" }), let id = messageID(cell) {
                    let y = cell.convert(cell.bounds, to: window).minY
                    let height = cell.bounds.height
                    let glyph = visibleGlyph(in: cell, viewport: t.convert(t.bounds, to: window), window: window)
                    rows.append(entry("near-\(offset)", "agentMessage", "近底部阅读时保留锚点")); sync()
                    try? await Task.sleep(for: .milliseconds(700))
                    if let kept = t.visibleCells.first(where: { messageID($0) == id }) {
                        let originDelta = abs(kept.convert(kept.bounds, to: window).minY - y)
                        var delta = originDelta
                        if let glyph {
                            let views = textViews(in: kept)
                            if views.indices.contains(glyph.0), views[glyph.0].text == glyph.1,
                               let start = views[glyph.0].position(from: views[glyph.0].beginningOfDocument, offset: glyph.2),
                               let end = views[glyph.0].position(from: start, offset: 1), let range = views[glyph.0].textRange(from: start, to: end) {
                                delta = abs(views[glyph.0].convert(views[glyph.0].firstRect(for: range), to: window).minY - glyph.3)
                            } else { delta = .greatestFiniteMagnitude }
                        }
                        nearBottomCellGeometry.append(["originDelta": originDelta, "beforeHeight": height, "afterHeight": kept.bounds.height, "glyphMeasured": glyph == nil ? 0 : 1])
                        nearBottomDeltas.append(delta); nearBottomPreserved = nearBottomPreserved && delta < 1 && originDelta < 1
                    } else { nearBottomPreserved = false }
                } else { nearBottomPreserved = false }
            }
            t.setContentOffset(.zero, animated: false)
            try? await Task.sleep(for: .milliseconds(300))
            scrollDuringProjection = true
            rows.append(entry("concurrent-scroll", "agentMessage", "投影期间移动阅读位置")); sync()
            try? await Task.sleep(for: .milliseconds(700))
            if let (id, y) = concurrentAnchor, let kept = t.visibleCells.first(where: { messageID($0) == id }) {
                concurrentScrollPreserved = abs(kept.convert(kept.bounds, to: window).minY - y) < 1
            }
            t.setContentOffset(CGPoint(x: 0, y: 400), animated: false)
            try? await Task.sleep(for: .milliseconds(300))
            NotificationCenter.default.post(name: Notification.Name("fixture.latest"), object: nil)
            rows.append(entry("latest-update", "agentMessage", "回到底部期间收到新消息")); sync()
            try? await Task.sleep(for: .milliseconds(900))
            returnToLatestPassed = abs(t.contentOffset.y) < 1 && t.visibleCells.contains { messageID($0) == "latest-update" }
            window.endEditing(true)
            try? await Task.sleep(for: .milliseconds(700))
        }
        var growingGlyphPreserved = !boundaryOnly
        var growingGlyphDelta: CGFloat = -1
        var growingGlyphIdentity = ""
        if boundaryOnly, let window = keyWindow, let t = table(in: window) {
            t.setContentOffset(CGPoint(x: 0, y: 200), animated: false)
            try? await Task.sleep(for: .milliseconds(300))
            if let cell = t.visibleCells.first(where: { messageID($0) == "a3" }), let index = rows.firstIndex(where: { $0["id"].text == "a3" }) {
                let viewport = t.convert(t.bounds, to: window)
                if let anchor = textViews(in: cell).compactMap({ view -> (String, Int, CGFloat)? in
                    guard !view.isEditable, let text = view.text else { return nil }
                    for offset in 0..<(text as NSString).length {
                        guard let start = view.position(from: view.beginningOfDocument, offset: offset), let end = view.position(from: start, offset: 1), let range = view.textRange(from: start, to: end) else { continue }
                        let rect = view.convert(view.firstRect(for: range), to: window)
                        if rect.height > 0, viewport.contains(rect) { return (text, offset, rect.minY) }
                    }
                    return nil
                }).first {
                    growingGlyphIdentity = anchor.0 + " @" + String(anchor.1)
                    rows[index] = entry("a3", "agentMessage", rows[index]["text"].text + (0..<8).map { "追加段落 \($0)：可见正文继续追加，需要保持阅读位置。\n\n" }.joined()); sync()
                    try? await Task.sleep(for: .milliseconds(700))
                    if let kept = t.visibleCells.first(where: { messageID($0) == "a3" }), let view = textViews(in: kept).first(where: { $0.text == anchor.0 }),
                       let start = view.position(from: view.beginningOfDocument, offset: anchor.1), let end = view.position(from: start, offset: 1), let range = view.textRange(from: start, to: end) {
                        growingGlyphDelta = abs(view.convert(view.firstRect(for: range), to: window).minY - anchor.2)
                        growingGlyphPreserved = growingGlyphDelta < 1
                    }
                }
            }
        }
        var glyphCases: [[String: Any]] = []
        if boundaryOnly {
            glyphCases.append(await verifyGlyphGrowth(name: "prefixParagraphs", body: (["说明扩展内容"] + Array(repeating: "说明", count: 39)).joined(separator: "\n\n"), suffix: "\n\n新增段落\n\n" + String(repeating: "追加内容。\n\n", count: 8)))
            glyphCases.append(await verifyGlyphGrowth(name: "duplicateParagraphs", body: Array(repeating: "完全重复段落，用于保持实际文字位置。", count: 40).joined(separator: "\n\n"), suffix: String(repeating: "\n\n新段落", count: 8)))
            glyphCases.append(await verifyGlyphGrowth(name: "growingParagraph", body: String(repeating: "当前段落持续保留已经显示的文字。", count: 100), suffix: String(repeating: "当前段落新增更多文字。", count: 20)))
            glyphCases.append(await verifyGlyphGrowth(name: "selectedParagraph", body: String(repeating: "正在选择的文字必须保持范围。", count: 100), suffix: String(repeating: "新增文字。", count: 40), select: true))
            glyphCases.append(await verifyGlyphGrowth(name: "growthThenMember", body: String(repeating: "保留正文的当前位置。", count: 100), suffix: String(repeating: "增长。", count: 40), appendMember: true))
            glyphCases.append(await verifyGlyphGrowth(name: "selectedGrowthThenMember", body: String(repeating: "已选择的长回复在下一条消息到达后保持。", count: 100), suffix: String(repeating: "增长。", count: 40), select: true, appendMember: true))
            for intent in ["change", "clear", "resign"] {
                glyphCases.append(await verifyGlyphGrowth(name: "selectionIntent-" + intent, body: String(repeating: "选区改变后不能恢复旧范围。", count: 100), suffix: String(repeating: "新增文字。", count: 40), select: true, selectionIntent: intent))
            }
        }
        var readingAnchorPreserved = false
        var readingAnchorDelta: CGFloat = -1
        var expandedHistoryPreserved = false
        var expandedHistoryDelta: CGFloat = -1
        if let window = keyWindow, let table = table(in: window) {
            let maxOffset = max(0, table.contentSize.height - table.bounds.height + table.adjustedContentInset.bottom)
            table.setContentOffset(CGPoint(x: 0, y: boundaryOnly ? maxOffset / 2 : min(800, maxOffset / 2)), animated: false)
            try? await Task.sleep(for: .milliseconds(600))
            if let cell = table.visibleCells.first(where: { messageID($0)?.hasPrefix("earlier-") == true }), let id = messageID(cell) {
                let before = cell.convert(cell.bounds, to: window).minY
                rows.append(entry("reading-update", "agentMessage", "阅读旧消息时收到的新回复")); sync()
                try? await Task.sleep(for: .milliseconds(700))
                if let retained = table.visibleCells.first(where: { messageID($0) == id }) {
                    readingAnchorDelta = abs(retained.convert(retained.bounds, to: window).minY - before)
                    readingAnchorPreserved = readingAnchorDelta < 1
                    let beforeExpansion = retained.convert(retained.bounds, to: window).minY
                    NotificationCenter.default.post(name: Notification.Name("fixture.earlier"), object: nil)
                    try? await Task.sleep(for: .milliseconds(700))
                    if let expanded = table.visibleCells.first(where: { messageID($0) == id }) {
                        expandedHistoryDelta = abs(expanded.convert(expanded.bounds, to: window).minY - beforeExpansion)
                        expandedHistoryPreserved = expandedHistoryDelta < 1 && (projections.last?["retained"] as? Int ?? 0) >= 120
                    }
                }
            }
        }
        timer?.invalidate(); timer = nil
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        try? JSONSerialization.data(withJSONObject: samples).write(to: root.appendingPathComponent("samples.json"))
        if performanceOnly {
            let gaps = zip(samples, samples.dropFirst()).map { (($0.1["time"] as! Double) - ($0.0["time"] as! Double)) * 1000 }.sorted()
            let result: [String: Any] = ["passed": queueUpdatePreserved && queueCountUpdated && !gaps.isEmpty && readingAnchorPreserved && expandedHistoryPreserved, "unrelatedQueueUpdatePreserved": queueUpdatePreserved, "queueCountUpdated": queueCountUpdated, "measurement": "frameIntervals", "keyboardStarted": keyboardStarted, "authenticatedSelectableParagraphs": model.authenticated, "maxFrameGapMs": gaps.last ?? 0, "p95FrameGapMs": gaps.isEmpty ? 0 : gaps[min(gaps.count - 1, Int(Double(gaps.count) * 0.95))], "over50Ms": gaps.filter { $0 > 50 }.count, "frameCount": gaps.count, "readingAnchorPreserved": readingAnchorPreserved, "expandedHistoryPreserved": expandedHistoryPreserved, "projections": projections, "timings": timings]
            try? JSONSerialization.data(withJSONObject: result).write(to: root.appendingPathComponent("timeline-result.json"))
            if let window = keyWindow { let image = UIGraphicsImageRenderer(size: window.bounds.size).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }; try? image.pngData()?.write(to: root.appendingPathComponent("timeline.png")) }
            return
        }
        let sendFrames = samples.filter { (1.0..<3.25).contains($0["time"] as! Double) }
        let animatedSendFrames = sendFrames.filter { frame in
            (frame["cells"] as! [[String: Any]]).contains { !($0["animations"] as! [String]).isEmpty }
        }.count
        let gaps = zip(samples, samples.dropFirst()).map { ($0.1["time"] as! Double) - ($0.0["time"] as! Double) }
        // A new outgoing status row can grow; existing message text must not collapse.
        let existingIDs = Set(samples.filter { ($0["time"] as! Double) < 1 }.flatMap { ($0["cells"] as! [[String: Any]]).compactMap { $0["messageID"] as? String } }.filter { !$0.isEmpty && $0 != "carryon:status" })
        var baselineHeights: [String: CGFloat] = [:]
        for frame in samples where (frame["time"] as! Double) < 1 {
            for cell in frame["cells"] as! [[String: Any]] {
                if let id = cell["messageID"] as? String, existingIDs.contains(id), baselineHeights[id] == nil { baselineHeights[id] = cell["height"] as? CGFloat }
            }
        }
        let existingCells = sendFrames.flatMap { $0["cells"] as! [[String: Any]] }.filter { existingIDs.contains($0["messageID"] as? String ?? "") }
        let unstableHeightFrames = existingCells.filter { cell in
            let height = cell["height"] as! CGFloat, baseline = baselineHeights[cell["messageID"] as! String]!
            return abs((cell["presentationHeight"] as! CGFloat) - height) > 1 || abs(height - baseline) > 1
        }.count
        let result: [String: Any] = ["readingAnchors": readingAnchors, "growingGlyphPreserved": growingGlyphPreserved, "growingGlyphDelta": growingGlyphDelta, "growingGlyphIdentity": growingGlyphIdentity, "glyphCases": glyphCases, "passed": glyphCases.allSatisfy { $0["passed"] as? Bool == true } && growingGlyphPreserved && keyboardStarted && latestVisible && returnToLatestPassed && concurrentScrollPreserved && nearBottomPreserved && queueUpdatePreserved && queueCountUpdated && !sendFrames.isEmpty && !existingCells.isEmpty && unstableHeightFrames == 0 && readingAnchorPreserved && expandedHistoryPreserved,
                                     "unrelatedQueueUpdatePreserved": queueUpdatePreserved, "queueCountUpdated": queueCountUpdated, "keyboardStarted": keyboardStarted, "longLatestVisible": latestVisible, "returnToLatestPassed": returnToLatestPassed, "concurrentScrollPreserved": concurrentScrollPreserved, "nearBottomPreserved": nearBottomPreserved, "nearBottomDeltas": nearBottomDeltas, "nearBottomCellGeometry": nearBottomCellGeometry, "expandedHistoryPreserved": expandedHistoryPreserved, "expandedHistoryDelta": expandedHistoryDelta, "readingAnchorPreserved": readingAnchorPreserved, "readingAnchorDelta": readingAnchorDelta,
                                     "measurement": "layoutRegressionIncludesScreenshots", "existingMessageCount": existingIDs.count, "existingCellSamples": existingCells.count, "unstableExistingHeightSamples": unstableHeightFrames,
                                     "existingBodyRenders": bodyRenders.filter { existingIDs.contains($0.key) }, "historyRows": rows.count, "maxFrameGapMs": (gaps.max() ?? 0) * 1000,
                                     "sendFrames": sendFrames.count, "animatedSendFrames": animatedSendFrames, "projections": projections, "timings": timings]
        try? JSONSerialization.data(withJSONObject: result).write(to: root.appendingPathComponent("timeline-result.json"))
        if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first?.windows.first {
            let image = UIGraphicsImageRenderer(size: window.bounds.size).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
            try? image.pngData()?.write(to: root.appendingPathComponent("timeline.png"))
        }
        print("FIXTURE_COMPLETE \(root.path)")
    }
    func recordTiming(_ notification: Notification) {
        guard start > 0, var value = notification.object as? [String: Any] else { return }
        value["time"] = CACurrentMediaTime() - start; timings.append(value)
    }
    func recordRender(_ notification: Notification) {
        guard start > 0, let id = notification.object as? String else { return }
        bodyRenders[id, default: 0] += 1
    }
    func recordProjection(_ notification: Notification) {
        guard start > 0, var measurement = notification.object as? [String: Any] else { return }
        measurement["time"] = CACurrentMediaTime() - start
        projections.append(measurement)
    }
    var keyWindow: UIWindow? { UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first?.windows.first }
    func table(in view: UIView) -> UITableView? {
        if let table = view as? UITableView { return table }
        return view.subviews.lazy.compactMap { self.table(in: $0) }.first
    }
    func scrollBeforeTransaction() {
        guard scrollDuringProjection, let window = keyWindow, let t = table(in: window) else { return }
        scrollDuringProjection = false
        t.setContentOffset(CGPoint(x: 0, y: 120), animated: false)
        t.layoutIfNeeded()
        if let cell = t.visibleCells.first(where: { messageID($0) != nil && messageID($0) != "carryon:status" }), let id = messageID(cell) {
            concurrentAnchor = (id, cell.convert(cell.bounds, to: window).minY)
        }
    }
    func verifyGlyphGrowth(name: String, body: String, suffix: String, select: Bool = false, selectionIntent: String? = nil, appendMember: Bool = false) async -> [String: Any] {
        guard let window = keyWindow, let t = table(in: window), let index = rows.firstIndex(where: { $0["id"].text == "a3" }) else { return ["name": name, "passed": false] }
        window.endEditing(true)
        rows[index] = entry("a3", "agentMessage", body); sync()
        try? await Task.sleep(for: .milliseconds(450))
        t.setContentOffset(CGPoint(x: 0, y: 200), animated: false)
        try? await Task.sleep(for: .milliseconds(300))
        guard let cell = t.visibleCells.first(where: { messageID($0) == "a3" }) else { return ["name": name, "passed": false, "reason": "missing cell"] }
        let views = textViews(in: cell)
        guard let anchor = visibleGlyph(in: cell, viewport: t.convert(t.bounds, to: window), window: window) else { return ["name": name, "passed": false, "reason": "missing glyph"] }
        let selection = NSRange(location: anchor.2, length: 2)
        if select { views[anchor.0].becomeFirstResponder(); views[anchor.0].selectedRange = selection }
        rows[index] = entry("a3", "agentMessage", body + suffix); sync()
        if appendMember {
            try? await Task.sleep(for: .milliseconds(250))
            rows.append(entry("glyph-member-" + name, "agentMessage", "正文更新之后紧接成员变化")); sync()
        }
        if let selectionIntent {
            try? await Task.sleep(for: .milliseconds(250))
            if let current = t.visibleCells.first(where: { messageID($0) == "a3" }) {
                let texts = textViews(in: current)
                if texts.indices.contains(anchor.0) {
                    if selectionIntent != "resign" { texts[anchor.0].selectedRange = NSRange(location: anchor.2, length: selectionIntent == "clear" ? 0 : 3) }
                    if selectionIntent != "change" { texts[anchor.0].resignFirstResponder() }
                }
            }
            NotificationCenter.default.post(name: .init("fixture.readingLayout"), object: nil)
            try? await Task.sleep(for: .milliseconds(300))
        } else { try? await Task.sleep(for: .milliseconds(700)) }
        guard let kept = t.visibleCells.first(where: { messageID($0) == "a3" }) else { return ["name": name, "passed": false, "reason": "lost cell", "visible": t.visibleCells.compactMap(messageID), "offset": t.contentOffset.y, "height": t.contentSize.height] }
        let retained = textViews(in: kept)
        guard retained.indices.contains(anchor.0), let start = retained[anchor.0].position(from: retained[anchor.0].beginningOfDocument, offset: anchor.2), let end = retained[anchor.0].position(from: start, offset: 1), let range = retained[anchor.0].textRange(from: start, to: end) else { return ["name": name, "passed": false, "reason": "lost glyph"] }
        let view = retained[anchor.0], delta = abs(view.convert(view.firstRect(for: range), to: window).minY - anchor.3)
        let selectionKept: Bool
        if let selectionIntent {
            selectionKept = view.selectedRange == NSRange(location: anchor.2, length: selectionIntent == "resign" ? 2 : selectionIntent == "clear" ? 0 : 3) && (selectionIntent != "change" ? !view.isFirstResponder : view.isFirstResponder)
        } else { selectionKept = !select || (view.selectedRange == selection && view.isFirstResponder) }
        window.endEditing(true)
        return ["name": name, "passed": delta < 1 && selectionKept, "delta": delta, "paragraph": anchor.0, "offset": anchor.2, "selectionKept": selectionKept, "textViewReplaced": views[anchor.0] !== view]
    }
    func visibleGlyph(in cell: UIView, viewport: CGRect, window: UIWindow) -> (Int, String, Int, CGFloat)? {
        for (paragraph, view) in textViews(in: cell).enumerated() where !view.isEditable {
            let text = view.text ?? ""
            for offset in 0..<(text as NSString).length {
                guard let start = view.position(from: view.beginningOfDocument, offset: offset), let end = view.position(from: start, offset: 1), let range = view.textRange(from: start, to: end) else { continue }
                let rect = view.convert(view.firstRect(for: range), to: window)
                if rect.height > 0, viewport.contains(rect) { return (paragraph, text, offset, rect.minY) }
            }
        }
        return nil
    }
    func textViews(in view: UIView) -> [UITextView] {
        (view as? UITextView).map { [$0] } ?? view.subviews.flatMap { textViews(in: $0) }
    }
    func editableText(in view: UIView) -> UITextView? {
        if let editor = view as? UITextView, editor.isEditable { return editor }
        return view.subviews.lazy.compactMap { self.editableText(in: $0) }.first
    }
    func messageID(_ view: UIView) -> String? {
        if let id = view.accessibilityIdentifier, id.hasPrefix("conversation-message-") { return String(id.dropFirst("conversation-message-".count)) }
        return view.subviews.lazy.compactMap(messageID).first
    }
    @objc func sample() {
        if performanceOnly { samples.append(["time": CACurrentMediaTime() - start]); return }
        guard let window = keyWindow else { return }
        // Keep instrumentation from traversing the entire hosting hierarchy every frame.
        // Revalidate ownership; a replacement table is discovered on the next sample.
        if sampledTable?.window !== window { sampledTable = table(in: window) }
        guard let t = sampledTable else { return }
        let samplingStart = CACurrentMediaTime()
        samples.append(["time": CACurrentMediaTime() - start, "contentHeight": t.contentSize.height, "offset": t.contentOffset.y, "cells": t.visibleCells.map { c in ["messageID": messageID(c) ?? "", "screenY": c.convert(c.bounds, to: window).minY, "row": t.indexPath(for: c)?.row ?? -1, "height": c.bounds.height, "presentationHeight": c.layer.presentation()?.bounds.height ?? c.bounds.height, "animations": c.layer.animationKeys() ?? []] as [String: Any] }])
        samples[samples.count - 1]["sampleMs"] = (CACurrentMediaTime() - samplingStart) * 1000
    }
}
