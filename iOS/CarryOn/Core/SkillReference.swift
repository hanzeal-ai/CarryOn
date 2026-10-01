import Foundation

/// Identity returned by the native skill catalog. The server revalidates it before sending.
public struct SkillReference: Codable, Equatable, Hashable, Sendable {
    public let name: String
    public let path: String
    public init(name: String, path: String) { self.name = name; self.path = path }
    public var value: JSONValue { .object(["name": .string(name), "path": .string(path)]) }
}
