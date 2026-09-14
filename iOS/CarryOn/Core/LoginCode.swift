import Foundation

public struct LoginCode: Sendable {
    public let address: ConsoleAddress
    public let id: String
    public let secret: String
    public init(_ raw: String) throws {
        guard var parts = URLComponents(string: raw), parts.query == nil,
              let fragment = parts.fragment, fragment.hasPrefix("carryon-login=") else { throw APIError("不是 CarryOn 登录二维码") }
        let values = fragment.dropFirst("carryon-login=".count).split(separator: ".", omittingEmptySubsequences: false)
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        guard values.count == 2, values[0].count == 32, values[1].count == 43,
              values.allSatisfy({ $0.unicodeScalars.allSatisfy { allowed.contains($0) } }) else { throw APIError("登录二维码无效") }
        parts.fragment = nil
        address = try ConsoleAddress(parts.string ?? "")
        id = String(values[0]); secret = String(values[1])
    }
}
