import Foundation

public struct WorkspaceBindingCode: Sendable {
    public let address: ConsoleAddress
    public let id: String
    public let secret: String
    public init(_ raw: String) throws {
        guard var parts = URLComponents(string: raw), parts.query == nil,
              let fragment = parts.fragment, fragment.hasPrefix("carryon-bind=") else { throw APIError("不是 CarryOn 工作区二维码") }
        let values = fragment.dropFirst("carryon-bind=".count).split(separator: ".", omittingEmptySubsequences: false)
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        guard values.count == 2, values[0].count == 32, values[1].count == 43,
              values.allSatisfy({ $0.unicodeScalars.allSatisfy { allowed.contains($0) } }) else { throw APIError("工作区二维码无效") }
        parts.fragment = nil
        address = try ConsoleAddress(parts.string ?? "")
        id = String(values[0]); secret = String(values[1])
    }
    public var body: JSONValue { .object(["id": .string(id), "secret": .string(secret)]) }
}
