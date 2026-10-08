
@MainActor private final class ConversationListGuardState {
    var epoch = 0
    var receipts: [Bool] = []
    var completed: Set<Int> = []
    var pages = 0
    var holdPages = false
    var pageWaiters: [Int: CheckedContinuation<Void, Never>] = [:]
}
@MainActor func runConversationListGuardChecks(in window: UIWindow) async -> [String: Bool] {
    let state = ConversationListGuardState()
    var checks: [String: Bool] = [:]
    let transaction = ConversationListTransaction()
    let first = Task { await transaction {}; state.completed.insert(1) }
    while transaction.version < 1 { await Task.yield() }
    let second = Task { await transaction {}; state.completed.insert(2) }
    while transaction.version < 2 { await Task.yield() }
    transaction.finish(version: 1)
    await first.value
    checks["oldCompletionDoesNotFinishNewTransaction"] = state.completed == [1] && transaction.pending.count == 1
    transaction.finish(version: 2); await second.value
    checks["bothTransactionWaitersFinishOnce"] = state.completed == [1, 2] && transaction.pending.isEmpty
    let rows = (0..<50).map { ConversationListRow(id: "guard-\($0)", configuration: nil, content: AnyView(Text("row \($0)").frame(height: 48))) }
    func parent(_ epoch: Int, _ rows: [ConversationListRow], _ scroll: ConversationListScroll? = nil) -> ConversationList {
        ConversationList(rows: rows, scope: "guard-\(epoch)", isCurrent: { state.epoch == epoch }, mayFollowLatest: { true }, onOffset: { _ in }, olderBoundaryID: rows.first?.id, canLoadEarlier: true, loadEarlier: { state.pages += 1; if state.holdPages { await withCheckedContinuation { state.pageWaiters[epoch] = $0 } } }, transaction: nil, scroll: scroll, didApply: { state.receipts.append($0) })
    }
    let table = UITableView(frame: CGRect(x: 0, y: 0, width: 375, height: 350), style: .plain)
    table.transform = CGAffineTransform(rotationAngle: .pi)
    table.rowHeight = UITableView.automaticDimension; table.estimatedRowHeight = 48
    table.register(UITableViewCell.self, forCellReuseIdentifier: "conversation-list-row")
    let coordinator = ConversationList.Coordinator(parent(0, rows))
    coordinator.attach(table); table.delegate = coordinator
    window.addSubview(table)
    defer { coordinator.mounted = false; coordinator.olderTask?.cancel(); state.pageWaiters.values.forEach { $0.resume() }; state.pageWaiters = [:]; table.removeFromSuperview() }
    func settled() async {
        for _ in 0..<50 {
            try? await Task.sleep(for: .milliseconds(10))
            if !coordinator.applying { table.layoutIfNeeded(); return }
        }
    }
    coordinator.update(); await settled()
    table.setContentOffset(CGPoint(x: 0, y: 100), animated: false)
    let late = ConversationListScroll(messageID: "guard-late", position: .middle)
    coordinator.parent = parent(0, rows, late); coordinator.update(); await settled()
    checks["missingTargetDoesNotConsumeOrScroll"] = coordinator.lastScroll != late.id && abs(table.contentOffset.y - 100) < 0.5
    let next = rows + [ConversationListRow(id: "guard-late", configuration: nil, content: AnyView(Text("late").frame(height: 48)))]
    coordinator.parent = parent(0, next, late); coordinator.update(); await settled()
    checks["lateTargetResolvesWhenPublished"] = coordinator.lastScroll == late.id && table.indexPathsForVisibleRows?.contains { coordinator.source?.itemIdentifier(for: $0) == "guard-late" } == true
    NotificationCenter.default.post(name: .init("fixture.prototypeGuardDetail"), object: ["lateOffset": table.contentOffset.y, "lateInsetTop": table.adjustedContentInset.top, "lateConsumed": coordinator.lastScroll == late.id, "lateVisible": table.indexPathsForVisibleRows?.contains { coordinator.source?.itemIdentifier(for: $0) == "guard-late" } == true])
    table.setContentOffset(CGPoint(x: 0, y: 100), animated: false)
    let cancelled = ConversationListScroll(messageID: "guard-15", position: .middle)
    coordinator.parent = parent(0, next, cancelled)
    coordinator.fixtureBeforeScrollValidation = { coordinator.parent = parent(0, next) }
    coordinator.applyScroll()
    checks["cancelDuringLayoutDoesNotExecuteOldScroll"] = coordinator.lastScroll != cancelled.id && abs(table.contentOffset.y - 100) < 0.5
    state.receipts = []
    let fresh = next + [ConversationListRow(id: "guard-epoch", configuration: nil, content: AnyView(Text("epoch").frame(height: 48)))]
    coordinator.parent = parent(0, fresh)
    coordinator.fixtureBeforeCompletion = {
        state.epoch = 1
        coordinator.parent = parent(1, fresh)
        table.setContentOffset(CGPoint(x: 0, y: 200), animated: false)
    }
    coordinator.update(); await settled()
    checks["staleEpochCompletionDoesNotRestore"] = abs(table.contentOffset.y - 200) < 0.5 && state.receipts.last == false
    coordinator.parent = parent(1, fresh); coordinator.update(); await settled()
    checks["newEpochPublishesAndCompletes"] = coordinator.scope == "guard-1" && state.receipts.last == true
    table.setContentOffset(CGPoint(x: 0, y: table.contentSize.height - table.bounds.height), animated: false)
    coordinator.checkPagination()
    try? await Task.sleep(for: .milliseconds(50))
    checks["visibleOlderBoundaryLoadsOnce"] = state.pages == 1
    coordinator.checkPagination(); try? await Task.sleep(for: .milliseconds(30))
    checks["sameOlderBoundaryDoesNotLoop"] = state.pages == 1
    table.setContentOffset(CGPoint(x: 0, y: 100), animated: false); coordinator.checkPagination()
    state.pages = 0
    table.setContentOffset(CGPoint(x: 0, y: table.contentSize.height - table.bounds.height), animated: false); coordinator.checkPagination()
    state.epoch = 2; coordinator.parent = parent(2, fresh); coordinator.update(); await settled()
    try? await Task.sleep(for: .milliseconds(50))
    checks["queuedOldEpochDoesNotBlockNewPagination"] = state.pages == 1 && coordinator.olderTask == nil && coordinator.scope == "guard-2"
    table.setContentOffset(CGPoint(x: 0, y: 100), animated: false); coordinator.checkPagination()
    state.pages = 0; state.holdPages = true
    table.setContentOffset(CGPoint(x: 0, y: table.contentSize.height - table.bounds.height), animated: false); coordinator.checkPagination()
    for _ in 0..<50 { if state.pageWaiters[2] != nil { break }; try? await Task.sleep(for: .milliseconds(10)) }
    let oldJob = coordinator.olderTask
    state.epoch = 3; coordinator.parent = parent(3, fresh); coordinator.update(); await settled()
    for _ in 0..<50 { if state.pageWaiters[3] != nil { break }; try? await Task.sleep(for: .milliseconds(10)) }
    let newToken = coordinator.olderToken, newJob = coordinator.olderTask
    state.pageWaiters.removeValue(forKey: 2)?.resume(); await oldJob?.value
    checks["cancelledOldTaskCannotClearNewTask"] = state.pages == 2 && coordinator.olderTask != nil && newToken != nil && coordinator.olderToken == newToken && state.pageWaiters[3] != nil
    state.pageWaiters.removeValue(forKey: 3)?.resume(); await newJob?.value
    checks["newPaginationTaskFinishesAfterOldCancellation"] = state.pages == 2 && coordinator.olderTask == nil && coordinator.olderToken == nil
    return checks
}
