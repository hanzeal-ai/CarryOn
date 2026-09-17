import Foundation
import Testing
@testable import CarryOnCore

private final class ProbeSocket: ConsoleSocket, @unchecked Sendable {
    private let lock = NSLock()
    private var callback: (@Sendable (Error?) -> Void)?
    private var closes = 0
    private var pendingSend: CheckedContinuation<Void, Error>?
    let responds: Bool
    init(responds: Bool) { self.responds = responds }
    func send(_ message: URLSessionWebSocketTask.Message) async throws {
        if responds { return }
        try await withCheckedThrowingContinuation { continuation in
            lock.withLock { pendingSend = continuation }
        }
    }
    func receive() async throws -> URLSessionWebSocketTask.Message {
        .string(#"{"type":"update","subscription":"test","resubscribe":true,"body":{"type":"update","threadId":null}}"#)
    }
    var closeCount: Int { lock.withLock { closes } }
    func sendPing(pongReceiveHandler: @escaping @Sendable (Error?) -> Void) {
        if responds { pongReceiveHandler(nil) }
        else { lock.withLock { callback = pongReceiveHandler } }
    }
    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        let pending = lock.withLock {
            closes += 1
            let result = callback; callback = nil; return result
        }
        pending?(URLError(.networkConnectionLost))
        let send = lock.withLock { let result = pendingSend; pendingSend = nil; return result }
        send?.resume(throwing: URLError(.networkConnectionLost))
    }
}

@Test func healthySocketSurvivesBackgroundAndResumeProbe() async throws {
    let socket = ProbeSocket(responds: true)
    let stream = ConsoleStream(task: socket, subscription: "test")
    stream.setForeground(false)
    #expect(socket.closeCount == 0)
    stream.setForeground(true)
    try await stream.checkHealth()
    #expect(socket.closeCount == 0)
}

@Test func unresponsiveResumeProbeClosesSocket() async {
    let socket = ProbeSocket(responds: false)
    let stream = ConsoleStream(task: socket, subscription: "test")
    do { try await stream.checkHealth(); Issue.record("Unresponsive socket must fail") }
    catch { #expect(socket.closeCount == 1) }
}

@Test func stalledSubscriptionClosesSocketInsteadOfBlockingResume() async throws {
    let socket = ProbeSocket(responds: false)
    let stream = ConsoleStream(task: socket, subscription: "test")
    _ = try await stream.next()
    #expect(stream.canResubscribe)
    do {
        try await stream.resubscribe(.object(["subscription": .string("new")]))
        Issue.record("Stalled subscription must fail")
    } catch { #expect(socket.closeCount == 1) }
}

@Test func initialSubscriptionCannotWaitIndefinitelyForSocketHandshake() async throws {
    let socket = ProbeSocket(responds: false)
    let stream = ConsoleStream(task: socket, subscription: "test")
    let clock = ContinuousClock(), start = clock.now
    do {
        try await stream.subscribe(.object(["subscription": .string("test")]))
        Issue.record("Initial handshake must have a deadline")
    } catch {
        #expect(socket.closeCount == 1)
        #expect(start.duration(to: clock.now) < .seconds(10))
    }
}

private final class HeartbeatSocket: ConsoleSocket, @unchecked Sendable {
    private let lock = NSLock()
    private var closed = false
    func send(_ message: URLSessionWebSocketTask.Message) async throws {}
    func sendPing(pongReceiveHandler: @escaping @Sendable (Error?) -> Void) { pongReceiveHandler(nil) }
    func receive() async throws -> URLSessionWebSocketTask.Message {
        try await Task.sleep(for: .milliseconds(10))
        if lock.withLock({ closed }) { throw URLError(.cancelled) }
        return .string(#"{"type":"ping"}"#)
    }
    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) { lock.withLock { closed = true } }
}

@Test func heartbeatsDoNotKeepMissingFirstSnapshotAlive() async throws {
    let stream = ConsoleStream(task: HeartbeatSocket(), subscription: "test", subscriptionTimeout: .milliseconds(50))
    let clock = ContinuousClock(), start = clock.now
    do {
        _ = try await stream.next()
        Issue.record("Heartbeats are not a usable subscription snapshot")
    } catch {
        #expect(error is APIError)
        #expect(start.duration(to: clock.now) < .seconds(2))
    }
}

@Test func cancellingInitialSubscriptionReleasesPendingSend() async throws {
    let socket = ProbeSocket(responds: false)
    let stream = ConsoleStream(task: socket, subscription: "test")
    let operation = Task { try await stream.subscribe(.object(["subscription": .string("test")])) }
    try await Task.sleep(for: .milliseconds(100))
    let clock = ContinuousClock(), start = clock.now
    operation.cancel()
    do { try await operation.value; Issue.record("Cancelled handshake must not succeed") }
    catch {
        #expect(socket.closeCount >= 1)
        #expect(start.duration(to: clock.now) < .seconds(2))
    }
}
