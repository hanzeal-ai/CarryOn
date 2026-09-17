import Foundation
import Observation

/// Disposable display data. Never use this cache to authorize an operation.
@MainActor @Observable public final class DisplaySnapshotCache {
    public struct Entry: Codable, Sendable {
        public let value: JSONValue
        public let updated: Date
        let bytes: Int
    }
    @Observable fileprivate final class Slot {
        var entry: Entry
        init(_ entry: Entry) { self.entry = entry }
    }
    private var entries: [String: Slot] = [:]
    private struct Flight {
        let id: UUID
        let task: Task<JSONValue, Error>
    }
    @ObservationIgnored private var requests: [String: Flight] = [:]
    @ObservationIgnored private var cleanupTask: Task<Void, Never>?
    @ObservationIgnored private var saveTask: Task<Void, Never>?
    @ObservationIgnored private var generation = UUID()
    @ObservationIgnored private let disk: SnapshotDisk?
    private let maxBytes: Int
    private let maxEntries: Int
    public init(directory: URL? = nil, maxBytes: Int = 8 * 1024 * 1024, maxEntries: Int = 32) {
        disk = directory.map { SnapshotDisk(directory: $0) }
        self.maxBytes = maxBytes; self.maxEntries = maxEntries
    }
    public func restore(owner: String) async throws {
        _ = resetMemory()
        let version = generation
        await cleanupTask?.value
        guard version == generation, let disk else { return }
        let saved = try await disk.restore(owner: owner, generation: version)
        guard version == generation else { return }
        entries = saved.filter { Date().timeIntervalSince($0.value.updated) < 86400 }.mapValues(Slot.init)
        trim()
    }
    public func value(_ key: String) -> JSONValue { entries[key]?.entry.value ?? .null }
    public func store(_ value: JSONValue, key: String, bytes: Int, now: Date = Date()) {
        guard bytes >= 0, bytes <= maxBytes else { entries.removeValue(forKey: key); scheduleSave(); return }
        let entry = Entry(value: value, updated: now, bytes: bytes)
        if let slot = entries[key] { slot.entry = entry }
        else { entries[key] = Slot(entry) }
        trim(); scheduleSave()
    }
    private func trim() {
        var bytes = entries.values.reduce(0) { $0 + $1.entry.bytes }
        for key in entries.keys.sorted(by: { entries[$0]!.entry.updated < entries[$1]!.entry.updated }) {
            guard entries.count > maxEntries || bytes > maxBytes else { break }
            bytes -= entries.removeValue(forKey: key)!.entry.bytes
        }
    }
    public func load(_ key: String, maxAge: TimeInterval, fetch: @escaping @MainActor @Sendable () async throws -> JSONValue) async throws -> JSONValue {
        if let entry = entries[key]?.entry, Date().timeIntervalSince(entry.updated) < maxAge { return entry.value }
        if let flight = requests[key] { return try await flight.task.value }
        let version = generation, requestID = UUID()
        let task = Task {
            defer { if requests[key]?.id == requestID { requests[key] = nil } }
            let value = try await fetch()
            let bytes = try await Task.detached(priority: .utility) { try value.encoded().count }.value
            guard generation == version, !Task.isCancelled else { throw CancellationError() }
            store(value, key: key, bytes: bytes)
            return value
        }
        requests[key] = Flight(id: requestID, task: task)
        return try await task.value
    }

    public func remove(prefix: String) {
        for key in entries.keys where key.hasPrefix(prefix) { entries.removeValue(forKey: key) }
        for key in requests.keys where key.hasPrefix(prefix) { requests.removeValue(forKey: key)?.task.cancel() }
        scheduleSave()
    }
    public func cancelRequests() {
        for flight in requests.values { flight.task.cancel() }
        requests = [:]
    }
    private func resetMemory() -> UUID {
        let previous = generation
        generation = UUID(); saveTask?.cancel(); saveTask = nil
        cancelRequests(); entries = [:]
        return previous
    }
    public func reset() {
        let previous = resetMemory()
        if let disk {
            let pending = cleanupTask
            cleanupTask = Task { await pending?.value; await disk.clear(generation: previous) }
        }
    }
    private func scheduleSave() {
        guard saveTask == nil, let disk else { return }
        let version = generation
        saveTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(10)) } catch { return }
            guard let self, self.generation == version else { return }
            let snapshot = self.entries.mapValues(\.entry)
            self.saveTask = nil
            await disk.save(snapshot, generation: version)
        }
    }
    public func flush() async {
        await cleanupTask?.value
        saveTask?.cancel(); saveTask = nil
        await disk?.save(entries.mapValues(\.entry), generation: generation)
    }
}

private actor SnapshotDisk {
    private let directory: URL
    private var file: URL?
    private var generation: UUID?
    init(directory: URL) { self.directory = directory }
    func restore(owner: String, generation: UUID) throws -> [String: DisplaySnapshotCache.Entry] {
        // The caller supplies a SHA-256 session fingerprint, never a credential or path.
        guard owner.count == 64, owner.allSatisfy({ $0.isHexDigit }) else { return [:] }
        self.generation = generation
        file = directory.appendingPathComponent(owner + ".json")
        try purge(except: file)
        let saved = try LocalFiles.read([String: DisplaySnapshotCache.Entry].self, from: file!) ?? [:]
        let recent = saved.filter { Date().timeIntervalSince($0.value.updated) < 86400 }
        if recent.count != saved.count { try LocalFiles.write(recent, to: file!) }
        return recent
    }
    func save(_ entries: [String: DisplaySnapshotCache.Entry], generation: UUID) {
        guard self.generation == generation, let file else { return }
        // Cache failures must not prevent reading live data; the next update retries.
        try? LocalFiles.write(entries, to: file)
    }
    func clear(generation: UUID) {
        guard self.generation == nil || self.generation == generation else { return }
        try? purge(except: nil)
        self.generation = nil; file = nil
    }
    private func purge(except retained: URL?) throws {
        let files: [URL]
        do { files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) }
        catch let error as CocoaError where error.code == .fileReadNoSuchFile { return }
        for candidate in files {
            let name = candidate.deletingPathExtension().lastPathComponent
            guard candidate.pathExtension == "json", name.count == 64, name.allSatisfy({ $0.isHexDigit }), candidate.lastPathComponent != retained?.lastPathComponent else { continue }
            try FileManager.default.removeItem(at: candidate)
        }
    }
}
