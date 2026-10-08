from pathlib import Path
p = source / "CarryOn/App/ConversationView.swift"
t = p.read_text().replace('    private var historyHeader: some View {', r'''    private var historyHeader: some View {
    let state = model.history == .null ? (model.historyFailure == nil ? "loading" : "failed") : model.historyFailure != nil ? "retainedFailure" : model.history["syncing"].bool == true ? "syncing" : "normal"
    let _ = NotificationCenter.default.post(name: .init("fixture.headerBody"), object: state)
    return''', 1)
t = t.replace('        }.padding(.horizontal, 16)\n    }\n    private var canLoadEarlier:', '        }.padding(.horizontal, 16).background(FixtureHeaderMarker())\n    }\n    private var canLoadEarlier:', 1)
t = t.replace('        .onChange(of: visibleCount)', '        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.userReadingIntent"))) { _ in navigationTracker.cancelReadingRestoration(); navigationPinned = false; restoreScroll = nil; navigationPreview = nil }\n        .onReceive(NotificationCenter.default.publisher(for: .init("fixture.navigationInspect"))) { _ in NotificationCenter.default.post(name: .init("fixture.navigationReceipt"), object: ["restoreTarget": restoreScroll?.messageID ?? "nil", "pendingTarget": pendingNavigation ?? "nil"]) }\n        .onChange(of: visibleCount)', 1)
t = t.replace('        let kind = item["type"].text', '        let _ = { if !item["asyncQuestions"].array.isEmpty { NotificationCenter.default.post(name: .init("fixture.questionRender"), object: ["readOnly": contentContext.isReadOnly]) } }()\n        let kind = item["type"].text', 1)
t = t.replace("AsyncQuestionView(question: question, threadID: threadID)", "AsyncQuestionView(question: question, threadID: threadID).background(FixtureQuestionMarker())")
p.write_text(t)
