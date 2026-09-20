import Testing
@testable import CarryOnCore

@MainActor private final class RefreshGate {
    private var continuation: CheckedContinuation<Void, Never>?
    var waiting: Bool { continuation != nil }
    func wait() async { await withCheckedContinuation { continuation = $0 } }
    func release() { let saved = continuation; continuation = nil; saved?.resume() }
}

@MainActor private func waitForRefresh(_ condition: () -> Bool) async throws {
    for _ in 0..<1000 {
        if condition() { return }
        await Task.yield()
    }
    try #require(condition())
}

@Test @MainActor func continuousArrivalsStillDisplayEachInFlightSnapshot() async throws {
    let queue = ConversationRefreshQueue(), gate = RefreshGate()
    var displayed: [String] = []
    var started: [String] = []
    func enqueue(_ text: String) {
        queue.request {
            started.append(text)
            await gate.wait() // New deltas arrive while timeline projection is suspended.
            displayed.append(text)
        }
    }
    enqueue("a")
    try await waitForRefresh { gate.waiting }
    for text in ["ab", "abc", "abcd"] { enqueue(text) }
    #expect(started == ["a"])
    gate.release()
    try await waitForRefresh { gate.waiting && started.count == 2 }
    #expect(displayed == ["a"])
    #expect(started == ["a", "abcd"])

    // Keep producing before each projection finishes; none needs a quiet period to display.
    for text in ["abcde", "abcdef", "abcdefg"] {
        let previousCount = started.count
        enqueue(text)
        gate.release()
        try await waitForRefresh { gate.waiting && started.count == previousCount + 1 }
        #expect(displayed.count == previousCount)
    }
    gate.release()
    try await waitForRefresh { displayed.last == "abcdefg" }
    #expect(displayed == ["a", "abcd", "abcde", "abcdef", "abcdefg"])
}

@Test @MainActor func refreshWaitsForDisplayTransactionAndRestartsAfterIdle() async throws {
    let queue = ConversationRefreshQueue(), display = RefreshGate()
    var events: [String] = []
    queue.request {
        events.append("first prepared")
        await display.wait()
        events.append("first displayed")
    }
    try await waitForRefresh { display.waiting }
    queue.request { events.append("obsolete") }
    queue.request { events.append("latest displayed") }
    #expect(events == ["first prepared"])
    display.release()
    try await waitForRefresh { events.last == "latest displayed" }
    #expect(events == ["first prepared", "first displayed", "latest displayed"])
    queue.request { events.append("after idle") }
    try await waitForRefresh { events.last == "after idle" }
}
