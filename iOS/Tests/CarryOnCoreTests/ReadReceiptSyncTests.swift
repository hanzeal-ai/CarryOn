import Foundation
import Testing
@testable import CarryOnCore

@MainActor private final class ReceiptGate {
    var continuation: CheckedContinuation<Void, Never>?
    func wait() async { await withCheckedContinuation { continuation = $0 } }
    func release() { continuation?.resume(); continuation = nil }
}
@MainActor private func waitFor(_ condition: () -> Bool) async throws {
    for _ in 0..<1000 { if condition() { return }; await Task.yield() }
    try #require(condition())
}

@Test @MainActor func receiptsCoalesceAndSerializeAndRememberConfirmation() async throws {
    let queue = ReadReceiptSync(), gate = ReceiptGate()
    var calls: [Int] = []
    let send: @MainActor (String, Int) async throws -> Void = { _, sequence in
        calls.append(sequence)
        if calls.count == 1 { await gate.wait() }
    }
    queue.enqueue(threadID: "a", sequence: 1, send: send, failure: { _, _ in Issue.record("Unexpected failure") })
    try await waitFor { gate.continuation != nil }
    for value in [1, 2, 5, 3, 5] { queue.enqueue(threadID: "a", sequence: value, send: send, failure: { _, _ in }) }
    #expect(calls == [1])
    gate.release()
    try await waitFor { calls == [1, 5] }
    queue.enqueue(threadID: "a", sequence: 5, send: send, failure: { _, _ in })
    queue.enqueue(threadID: "b", sequence: 2, send: send, failure: { _, _ in })
    try await waitFor { calls == [1, 5, 2] }
    queue.reset()
}

@Test @MainActor func transientBusyRetriesLatestCursorWithoutLogging() async throws {
    let gate = ReceiptGate()
    var delays: [Duration] = [], calls: [Int] = [], failures = 0
    let queue = ReadReceiptSync(sleep: { delay in delays.append(delay); await gate.wait() })
    let send: @MainActor (String, Int) async throws -> Void = { _, sequence in
        calls.append(sequence)
        if calls.count == 1 { throw APIError("设备正忙", status: 503) }
    }
    queue.enqueue(threadID: "a", sequence: 1, send: send, failure: { _, _ in failures += 1 })
    try await waitFor { gate.continuation != nil }
    queue.enqueue(threadID: "a", sequence: 8, send: send, failure: { _, _ in failures += 1 })
    gate.release()
    try await waitFor { calls == [1, 8] }
    #expect(delays == [.milliseconds(500)])
    #expect(failures == 0)
    queue.reset()
}

@Test @MainActor func persistentBusyLogsOnceAndSlowsRetries() async throws {
    let gate = ReceiptGate()
    var delays: [Duration] = [], logs = 0, attempts = 0
    let queue = ReadReceiptSync(sleep: { delay in
        delays.append(delay)
        if delays.count == 5 { await gate.wait() }
    })
    queue.enqueue(threadID: "a", sequence: 1, send: { _, _ in
        attempts += 1; throw APIError("设备正忙", status: 503)
    }, failure: { _, persistent in #expect(persistent); logs += 1 })
    try await waitFor { gate.continuation != nil }
    #expect(attempts == 5)
    #expect(logs == 1)
    #expect(delays == [.milliseconds(500), .seconds(1), .seconds(2), .seconds(30), .seconds(30)])
    queue.reset(); gate.release()
}

@Test @MainActor func resetDiscardsOldWorkspaceCompletion() async throws {
    let queue = ReadReceiptSync(), gate = ReceiptGate()
    var oldCalls = 0, newCalls = 0
    queue.enqueue(threadID: "same", sequence: 100, send: { _, _ in oldCalls += 1; await gate.wait() }, failure: { _, _ in Issue.record("Stale failure") })
    try await waitFor { gate.continuation != nil }
    queue.reset()
    queue.enqueue(threadID: "same", sequence: 1, send: { _, _ in newCalls += 1 }, failure: { _, _ in })
    gate.release()
    try await waitFor { newCalls == 1 }
    #expect(oldCalls == 1)
    queue.reset()
}

@Test @MainActor func authenticationFailureIsNotHiddenOrRetried() async throws {
    var reports = 0, attempts = 0
    let queue = ReadReceiptSync(sleep: { _ in Issue.record("Authentication failure must not retry") })
    queue.enqueue(threadID: "a", sequence: 1, send: { _, _ in
        attempts += 1; throw APIError("登录已失效", status: 401)
    }, failure: { error, persistent in
        #expect((error as? APIError)?.status == 401)
        #expect(!persistent)
        reports += 1
    })
    try await waitFor { reports == 1 }
    #expect(attempts == 1)
    queue.reset()
}
