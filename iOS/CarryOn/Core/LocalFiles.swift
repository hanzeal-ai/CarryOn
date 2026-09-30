import Foundation
import Observation
import CryptoKit

public enum LocalFiles {
    public static var directory: URL {
        URL.applicationSupportDirectory.appendingPathComponent("CarryOn", isDirectory: true)
    }
    public static func read<Value: Decodable>(_ type: Value.Type, from url: URL) throws -> Value? {
        do { return try JSONDecoder().decode(type, from: Data(contentsOf: url)) }
        catch let error as CocoaError where error.code == .fileReadNoSuchFile { return nil }
    }
    public static func write<Value: Encodable>(_ value: Value, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        var options: Data.WritingOptions = .atomic
        #if os(iOS)
        options.insert(.completeFileProtection)
        #endif
        try JSONEncoder().encode(value).write(to: url, options: options)
        var resource = url
        var attributes = URLResourceValues()
        attributes.isExcludedFromBackup = true
        try resource.setResourceValues(attributes)
    }
}

public struct DraftSnapshot: Codable, Sendable {
    public var texts: [String: String]
    public var images: [String: [String]]
    public init(texts: [String: String] = [:], images: [String: [String]] = [:]) {
        self.texts = texts.filter { !$0.value.isEmpty }
        self.images = images.filter { !$0.value.isEmpty }
    }
}

public struct WorkspacePreferences {
    private let defaults: UserDefaults
    public init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    public func selectedDevice(server: String, available: [String]) -> String {
        let saved = defaults.dictionary(forKey: "carryon.selectedDevices.v1")?[server] as? String
        return saved.flatMap { available.contains($0) ? $0 : nil } ?? available.first ?? ""
    }
    public func selectDevice(_ id: String, server: String) {
        guard !id.isEmpty else { return }
        var selections = defaults.dictionary(forKey: "carryon.selectedDevices.v1") ?? [:]
        selections[server] = id
        defaults.set(selections, forKey: "carryon.selectedDevices.v1")
    }
}


@MainActor @Observable
public final class DraftStore {
    public var texts: [String: String] = [:] { didSet { scheduleSave() } }
    public var images: [String: [String]] = [:] { didSet { scheduleSave() } }
    private let file: URL
    private var activeFile: URL?
    private struct Save: Sendable {
        let id = UUID()
        let snapshot: DraftSnapshot
        let complete: Bool
    }
    private var unsaved: [URL: Save] = [:]
    @ObservationIgnored private var queued: [URL: Save] = [:]
    @ObservationIgnored private var writer: Task<Void, Never>?
    @ObservationIgnored private let write: @Sendable (DraftSnapshot, URL) async throws -> Void
    private var dirty = false
    private let report: (String, String) -> Void
    private var loaded = false
    private var generation = UUID()
    private var pendingSave: Task<Void, Never>?

    public init(file: URL = LocalFiles.directory.appendingPathComponent("drafts-v1.json"),
                write: @escaping @Sendable (DraftSnapshot, URL) async throws -> Void = { snapshot, file in
                    try await Task.detached(priority: .utility) { try LocalFiles.write(snapshot, to: file) }.value
                },
                report: @escaping (String, String) -> Void) {
        self.file = file; self.write = write; self.report = report
    }
    public func load(scope: String) async {
        reset()
        generation = UUID()
        let digest = SHA256.hash(data: Data(scope.utf8)).map { String(format: "%02x", $0) }.joined()
        let file = file.deletingPathExtension().appendingPathExtension(digest + ".json")
        activeFile = file
        let version = generation
        loaded = false
        pendingSave?.cancel()
        do {
            // Finish earlier writes before reading this account again.
            await writer?.value
            guard version == generation, !Task.isCancelled else { return }
            let saved = try await Task.detached(priority: .userInitiated) {
                try LocalFiles.read(DraftSnapshot.self, from: file) ?? DraftSnapshot()
            }.value
            guard version == generation, !Task.isCancelled else { return }
            if let pending = unsaved[file] {
                texts = pending.complete ? pending.snapshot.texts : saved.texts.merging(pending.snapshot.texts) { _, new in new }
                images = pending.complete ? pending.snapshot.images : saved.images.merging(pending.snapshot.images) { _, new in new }
            } else {
                texts = saved.texts; images = saved.images
            }
            loaded = true
            dirty = unsaved[file] != nil
            if dirty { save() }
        } catch {
            guard version == generation, !Task.isCancelled else { return }
            texts = unsaved[file]?.snapshot.texts ?? [:]
            images = unsaved[file]?.snapshot.images ?? [:]
            report("草稿文件无法读取，原文件已保留；当前编辑暂不能持久保存", "读取草稿")
        }
    }
    private func scheduleSave() {
        guard loaded else { return }
        dirty = true
        pendingSave?.cancel()
        pendingSave = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
            self?.save()
        }
    }
    /// Queue the latest snapshot. Use flush() when durable completion is required.
    public func save() {
        pendingSave?.cancel(); pendingSave = nil
        guard let activeFile else { return }
        var snapshot = DraftSnapshot()
        snapshot.texts = texts; snapshot.images = images
        guard loaded else {
            if !texts.isEmpty || !images.isEmpty { unsaved[activeFile] = Save(snapshot: snapshot, complete: unsaved[activeFile]?.complete ?? false) }
            return
        }
        guard dirty else { return }
        dirty = false
        let save = Save(snapshot: DraftSnapshot(texts: texts, images: images), complete: true)
        unsaved[activeFile] = save; queued[activeFile] = save
        guard writer == nil else { return }
        writer = Task {
            defer { writer = nil }
            while let file = queued.keys.first, let save = queued.removeValue(forKey: file) {
                do {
                    try await write(save.snapshot, file)
                    if unsaved[file]?.id == save.id { unsaved.removeValue(forKey: file) }
                } catch {
                    report("草稿未能保存到本机，已暂存在内存中；请恢复存储后重新登录当前账号，退出应用前不要清理进程", "保存草稿")
                }
            }
        }
    }
    @discardableResult public func flush() async -> Bool {
        save()
        await writer?.value
        return unsaved.isEmpty
    }
    public func reset() {
        save(); loaded = false; dirty = false; activeFile = nil; generation = UUID()
        texts = [:]; images = [:]
    }
}
