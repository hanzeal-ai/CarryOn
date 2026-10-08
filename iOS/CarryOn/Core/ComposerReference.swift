import Foundation

/// Identity returned by the native skill catalog. The server revalidates it before sending.
public struct ComposerReference: Codable, Equatable, Hashable, Sendable {
    public let name: String
    public let path: String
    public let offset: Int?
    public let displayName: String?
    public let iconData: String?
    public init(name: String, path: String, offset: Int? = nil, displayName: String? = nil, iconData: String? = nil) { self.name = name; self.path = path; self.offset = offset; self.displayName = displayName; self.iconData = iconData }
    public var label: String { if let displayName, !displayName.isEmpty { return displayName }; return name }
    public var isMention: Bool { path.hasPrefix("app://") || path.hasPrefix("plugin://") }
    public var value: JSONValue { .object(["name": .string(name), "path": .string(path)]) }
}
