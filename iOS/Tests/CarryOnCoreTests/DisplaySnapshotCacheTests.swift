import Foundation
import Observation
import Testing
@testable import CarryOnCore

@MainActor private final class SnapshotGate {
    var calls = 0
    var pending: CheckedContinuation<JSONValue, Never>?
    func fetch() async -> JSONValue {
        calls += 1
        return await withCheckedContinuation { pending = $0 }
    }
    func wait() async { while pending == nil { await Task.yield() } }
    func finish(_ value: JSONValue) { pending?.resume(returning: value); pending = nil }
}

@Test @MainActor func snapshotCacheDeduplicatesAndKeepsOldContentDuringRefreshFailure() async throws {
    let cache = DisplaySnapshotCache(), gate = SnapshotGate()
    let old: JSONValue = .object(["title": .string("cached")])
    cache.store(old, key: "workspace/status", bytes: 20, now: .distantPast)
    let first = Task { try await cache.load("workspace/status", maxAge: 30) { await gate.fetch() } }
    await gate.wait()
    let second = Task { try await cache.load("workspace/status", maxAge: 30) { await gate.fetch() } }
    await Task.yield()
    #expect(cache.value("workspace/status") == old)
    gate.finish(.object(["title": .string("fresh")]))
    #expect(try await first.value == second.value)
    #expect(gate.calls == 1)
    let fresh = cache.value("workspace/status")
    await #expect(throws: APIError.self) {
        try await cache.load("workspace/status", maxAge: 0) { throw APIError("offline") }
    }
    #expect(cache.value("workspace/status") == fresh)
    _ = try await cache.load("workspace/status", maxAge: 30) { Issue.record("A fresh entry should not fetch"); return .null }
}

@Test @MainActor func snapshotCacheResetRejectsLateResponse() async throws {
    let cache = DisplaySnapshotCache(), gate = SnapshotGate()
    let request = Task { try await cache.load("old-account/history", maxAge: 0) { await gate.fetch() } }
    await gate.wait()
    cache.reset()
    gate.finish(.object(["secret": .string("old-account")]))
    await #expect(throws: CancellationError.self) { try await request.value }
    #expect(cache.value("old-account/history") == .null)
}

@Test @MainActor func snapshotCacheRemovalRejectsLateResponseAndPreservesOtherWorkspace() async throws {
    let cache = DisplaySnapshotCache(), gate = SnapshotGate()
    cache.store(.string("B"), key: "server/B/status", bytes: 3)
    let request = Task { try await cache.load("server/A/status", maxAge: 0) { await gate.fetch() } }
    await gate.wait()
    cache.remove(prefix: "server/A/")
    gate.finish(.string("removed"))
    await #expect(throws: CancellationError.self) { try await request.value }
    #expect(cache.value("server/A/status") == .null)
    #expect(cache.value("server/B/status") == .string("B"))
}

@Test @MainActor func snapshotCacheBoundsEntriesAndBytes() {
    let cache = DisplaySnapshotCache(maxBytes: 10, maxEntries: 2)
    cache.store(.string("one"), key: "one", bytes: 5, now: Date(timeIntervalSince1970: 1))
    cache.store(.string("two"), key: "two", bytes: 5, now: Date(timeIntervalSince1970: 2))
    cache.store(.string("three"), key: "three", bytes: 5)
    #expect(cache.value("one") == .null)
    #expect(cache.value("two") != .null)
    cache.store(.string("too large"), key: "three", bytes: 11)
    #expect(cache.value("three") == .null)
}

@Test @MainActor func snapshotCachePersistsOnlyForMatchingSessionAndExpiresOldEntries() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let owner = String(repeating: "a", count: 64), other = String(repeating: "b", count: 64)
    let first = DisplaySnapshotCache(directory: directory)
    try await first.restore(owner: owner)
    first.store(.string("message"), key: "server/device/history", bytes: 9)
    first.store(.string("expired"), key: "expired", bytes: 9, now: Date().addingTimeInterval(-86401))
    await first.flush()
    let reopened = DisplaySnapshotCache(directory: directory)
    try await reopened.restore(owner: owner)
    #expect(reopened.value("server/device/history") == .string("message"))
    #expect(reopened.value("expired") == .null)
    let otherAccount = DisplaySnapshotCache(directory: directory)
    try await otherAccount.restore(owner: other)
    #expect(otherAccount.value("server/device/history") == .null)
    #expect(!FileManager.default.fileExists(atPath: directory.appendingPathComponent(owner + ".json").path))
    reopened.reset()
    await reopened.flush()
    let loggedOut = DisplaySnapshotCache(directory: directory)
    try await loggedOut.restore(owner: owner)
    #expect(loggedOut.value("server/device/history") == .null)
}

@Test @MainActor func cancelledRequestCannotReplaceOrReleaseNewRequestForSameKey() async throws {
    let cache = DisplaySnapshotCache(), old = SnapshotGate(), fresh = SnapshotGate()
    let first = Task { try await cache.load("workspace/status", maxAge: 0) { await old.fetch() } }
    await old.wait()
    let duplicate = Task { try await cache.load("workspace/status", maxAge: 0) { Issue.record("Should join first request"); return .null } }
    await Task.yield()
    cache.cancelRequests()
    let second = Task { try await cache.load("workspace/status", maxAge: 0) { await fresh.fetch() } }
    await fresh.wait()
    old.finish(.string("old"))
    await #expect(throws: CancellationError.self) { try await first.value }
    await #expect(throws: CancellationError.self) { try await duplicate.value }
    let joined = Task { try await cache.load("workspace/status", maxAge: 0) { Issue.record("Old cleanup must not release the new flight"); return .null } }
    await Task.yield()
    fresh.finish(.string("new"))
    #expect(try await second.value == .string("new"))
    #expect(try await joined.value == .string("new"))
    #expect(cache.value("workspace/status") == .string("new"))
}

private final class CacheChangeCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    func increment() { lock.withLock { count += 1 } }
    var value: Int { lock.withLock { count } }
}
@Test @MainActor func backgroundHistoryUpdatesDoNotInvalidateSettingsReaders() {
    let cache = DisplaySnapshotCache(), changes = CacheChangeCounter()
    cache.store(.number(80), key: "usage", bytes: 2)
    cache.store(.string("before"), key: "history", bytes: 8)
    _ = withObservationTracking { cache.value("usage") } onChange: { changes.increment() }
    cache.store(.string("streaming message"), key: "history", bytes: 19)
    #expect(changes.value == 0)
    cache.store(.number(79), key: "usage", bytes: 2)
    #expect(changes.value == 1)
}

@Test @MainActor func unauthenticatedColdStartRemovesPreviousSessionFiles() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let owner = String(repeating: "a", count: 64)
    let previous = DisplaySnapshotCache(directory: directory)
    try await previous.restore(owner: owner)
    previous.store(.string("private"), key: "history", bytes: 9)
    await previous.flush()
    let cold = DisplaySnapshotCache(directory: directory)
    cold.reset(); await cold.flush()
    #expect(!FileManager.default.fileExists(atPath: directory.appendingPathComponent(owner + ".json").path))
}
