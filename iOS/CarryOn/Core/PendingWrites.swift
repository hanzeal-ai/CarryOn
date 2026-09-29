import Foundation
import CryptoKit

/// Persists only request identifiers and payload hashes, never prompts or credentials.
@MainActor public final class PendingWrites {
    private struct Entry: Codable { let digest: String; let requestID: String }
    private var entries: [String: Entry]
    private let defaults: UserDefaults
    private let storageKey: String
    private let unreadable: Bool
    public init(defaults: UserDefaults = .standard, storageKey: String = "carryon.pendingWrites.v1") {
        self.defaults = defaults; self.storageKey = storageKey
        let data = defaults.data(forKey: storageKey)
        let decoded = data.flatMap { try? JSONDecoder().decode([String: Entry].self, from: $0) }
        entries = decoded ?? [:]
        unreadable = data != nil && decoded == nil
    }
    private func hash(_ text: String) -> String { SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined() }
    public func requestID(scope: String, target: String, path: String, body: JSONValue) throws -> String {
        guard !unreadable else { throw APIError("本地请求记录无法读取，已暂停写入。请保留 App 数据并核对原请求，勿重新安装后重发。") }
        let prefix = hash(scope + "\n" + target)
        let digest = hash(path + "\n" + String(decoding: try body.encoded(), as: UTF8.self))
        let key = prefix + ":" + digest
        if let entry = entries[key] { return entry.requestID }
        // Preserve an unresolved request saved by an earlier installed client.
        if let entry = entries[prefix], entry.digest == digest {
            entries[key] = entry; entries.removeValue(forKey: prefix); try save()
            return entry.requestID
        }
        let id = UUID().uuidString
        entries[key] = Entry(digest: digest, requestID: id)
        try save()
        return id
    }
    public func reconcile(scope: String, job: JSONValue) throws {
        guard ["accepted", "completed", "inProgress", "acknowledged", "failed", "interrupted"].contains(job["state"].text) else { return }
        if job["kind"].text == "create" && job["state"].text == "accepted" && job["createdThreadId"].string == nil { return }
        try resolve(scope: scope, target: job["threadId"].text, requestID: job["id"].text)
        try resolve(scope: scope, target: "new", requestID: job["id"].text)
        if let project = job["creationProject"]["groupId"].string {
            try resolve(scope: scope, target: "new:" + project, requestID: job["id"].text)
        }
    }
    public func resolve(scope: String, target: String, requestID: String) throws {
        let prefix = hash(scope + "\n" + target)
        entries = entries.filter { key, entry in
            !((key == prefix || key.hasPrefix(prefix + ":")) && entry.requestID == requestID)
        }
        try save()
    }
    private func save() throws { defaults.set(try JSONEncoder().encode(entries), forKey: storageKey) }
}
