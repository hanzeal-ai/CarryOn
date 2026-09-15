import SwiftUI
import CarryOnCore

// Simulator-only entry point. Copy over CarryOnApp.swift in an isolated iOS checkout.
// Uses the real ConversationView with local snapshots; no login or message API is invoked.
@main struct CarryOnApp: App {
    @State private var fixture = TimelineFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack { ConversationView(thread: fixture.thread) }.environment(fixture.model)
                .task { await fixture.run() }
        }
    }
}
@MainActor @Observable final class TimelineFixture: NSObject {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("fixture"), "title": .string("时间线回归")]))
    var rows: [JSONValue] = []
    var samples: [[String: Any]] = []
    var timer: CADisplayLink?
    var start = 0.0
    func entry(_ id: String, _ type: String, _ text: String) -> JSONValue {
        .object(["id": .string(id), "type": .string(type), "title": .string(text), "text": .string(text), "status": .string("completed")])
    }
    func sync() {
        model.history = .object(["timeline": .array(rows), "status": .object(["state": .string("idle")])])
        model.historyRevision += 1
    }
    func run() async {
        model.selectedThread = thread
        rows = [entry("turn1", "turn", "第 1 轮"), entry("u1", "userMessage", "检查会话更新时的气泡高度"), entry("a1", "agentMessage", "这是一段已有回复。\n\n发送新消息时，这段内容应保持可见，不能先压缩再展开。\n\n- 保留内容\n- 保留布局\n- 连续更新"), entry("turn2", "turn", "第 2 轮"), entry("u2", "userMessage", "继续检查"), entry("a2", "agentMessage", "已有回复第二段。\n\n发送中的状态变化不应导致已有气泡重复播放高度动画。")]
        sync()
        try? await Task.sleep(for: .seconds(3))
        start = CACurrentMediaTime()
        timer = CADisplayLink(target: self, selector: #selector(sample)); timer?.add(to: .main, forMode: .common)
        try? await Task.sleep(for: .seconds(1))
        model.outgoing["send"] = .object(["id": .string("send"), "scope": .string(model.scope), "threadId": .string("fixture"), "prompt": .string("hello"), "state": .string("sending")])
        try? await Task.sleep(for: .seconds(1))
        rows += [entry("turn3", "turn", "第 3 轮"), entry("u3", "userMessage", "hello")]; sync()
        try? await Task.sleep(for: .milliseconds(250))
        model.outgoing.removeAll()
        try? await Task.sleep(for: .seconds(1))
        rows.append(entry("a3", "agentMessage", "开始回复")); sync()
        for n in 1...5 {
            try? await Task.sleep(for: .milliseconds(200))
            rows[rows.count - 1] = entry("a3", "agentMessage", String(repeating: "回复持续追加，旧气泡保持稳定。\n\n", count: n)); sync()
        }
        try? await Task.sleep(for: .seconds(1))
        timer?.invalidate(); timer = nil
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        try? JSONSerialization.data(withJSONObject: samples).write(to: root.appendingPathComponent("samples.json"))
        let sendFrames = samples.filter { (1.0..<3.25).contains($0["time"] as! Double) }
        let animatedSendFrames = sendFrames.filter { frame in
            (frame["cells"] as! [[String: Any]]).contains { !($0["animations"] as! [String]).isEmpty }
        }.count
        let result: [String: Any] = ["passed": !sendFrames.isEmpty && animatedSendFrames == 0,
                                     "sendFrames": sendFrames.count, "animatedSendFrames": animatedSendFrames]
        try? JSONSerialization.data(withJSONObject: result).write(to: root.appendingPathComponent("result.json"))
        print("FIXTURE_COMPLETE \(root.path)")
    }
    @objc func sample() {
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first?.windows.first else { return }
        func table(_ v: UIView) -> UITableView? { if let t = v as? UITableView { return t }; return v.subviews.lazy.compactMap(table).first }
        guard let t = table(window) else { return }
        samples.append(["time": CACurrentMediaTime() - start, "contentHeight": t.contentSize.height, "offset": t.contentOffset.y, "cells": t.visibleCells.map { c in ["row": t.indexPath(for: c)?.row ?? -1, "height": c.bounds.height, "presentationHeight": c.layer.presentation()?.bounds.height ?? c.bounds.height, "animations": c.layer.animationKeys() ?? []] as [String: Any] }])
    }
}
