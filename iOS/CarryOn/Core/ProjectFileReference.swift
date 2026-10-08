import Foundation

/// A native search result; the server rechecks its query and project membership.
public struct ProjectFileReference: Codable, Equatable, Hashable, Identifiable, Sendable {
    public let name: String
    public let path: String
    public let query: String
    public var id: String { path }
    public init(name: String, path: String, query: String) {
        self.name = name; self.path = path; self.query = query
    }
    public var value: JSONValue { .object(["name": .string(name), "path": .string(path), "query": .string(query)]) }
}
