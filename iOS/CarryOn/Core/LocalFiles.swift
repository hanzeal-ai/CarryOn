import Foundation

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
