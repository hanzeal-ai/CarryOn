import Foundation
import Security

public protocol SessionCredentials: Sendable {
    func load(server: String) throws -> String?
    func save(_ token: String, server: String) throws
    func remove(server: String) throws
    func remove(server: String, matching token: String) throws
}

/// Stores the revocable console session, never the login password/token.
public struct KeychainSessionCredentials: SessionCredentials {
    private static let lock = NSLock()
    public init() {}
    public func load(server: String) throws -> String? { try Self.lock.withLock { try loadUnlocked(server: server) } }
    public func save(_ token: String, server: String) throws { try Self.lock.withLock { try saveUnlocked(token, server: server) } }
    public func remove(server: String) throws { try Self.lock.withLock { try removeUnlocked(server: server) } }
    public func remove(server: String, matching token: String) throws {
        try Self.lock.withLock {
            if try loadUnlocked(server: server) == token { try removeUnlocked(server: server) }
        }
    }
    private func query(_ server: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.hanzeal.carryon.console-session",
         kSecAttrAccount as String: server]
    }
    private func loadUnlocked(server: String) throws -> String? {
        var lookup = query(server)
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data,
              let token = String(data: data, encoding: .utf8), !token.isEmpty else {
            throw APIError("无法读取安全保存的登录状态（\(status)）")
        }
        return token
    }
    private func saveUnlocked(_ token: String, server: String) throws {
        let values: [String: Any] = [kSecValueData as String: Data(token.utf8),
                                    kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var status = SecItemUpdate(query(server) as CFDictionary, values as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query(server).merging(values) { _, new in new } as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw APIError("无法安全保存登录状态（\(status)）") }
    }
    private func removeUnlocked(server: String) throws {
        let status = SecItemDelete(query(server) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw APIError("无法清除安全保存的登录状态（\(status)）")
        }
    }
}
