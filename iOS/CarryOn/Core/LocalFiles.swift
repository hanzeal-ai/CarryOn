import Foundation
import Observation

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
    private let report: (String, String) -> Void
    private var loaded = false
    private var generation = UUID()
    private var pendingSave: Task<Void, Never>?

    public init(file: URL = LocalFiles.directory.appendingPathComponent("drafts-v1.json"),
                report: @escaping (String, String) -> Void) {
        self.file = file; self.report = report
    }
    public func load() async {
        generation = UUID()
        let version = generation, file = file
        loaded = false
        pendingSave?.cancel()
        do {
            let saved = try await Task.detached(priority: .userInitiated) {
                try LocalFiles.read(DraftSnapshot.self, from: file) ?? DraftSnapshot()
            }.value
            guard version == generation, !Task.isCancelled else { return }
            texts = saved.texts; images = saved.images; loaded = true
        } catch {
            guard version == generation, !Task.isCancelled else { return }
            report("草稿文件无法读取，原文件已保留；当前编辑暂不能持久保存", "读取草稿")
        }
    }
    private func scheduleSave() {
        guard loaded else { return }
        pendingSave?.cancel()
        pendingSave = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
            self?.save()
        }
    }
    public func save() {
        pendingSave?.cancel(); pendingSave = nil
        guard loaded else { return }
        do { try LocalFiles.write(DraftSnapshot(texts: texts, images: images), to: file) }
        catch { report("草稿未能保存到本机，当前内容仍保留在页面中", "保存草稿") }
    }
    public func reset() {
        save(); loaded = false; generation = UUID()
        texts = [:]; images = [:]
    }
}
