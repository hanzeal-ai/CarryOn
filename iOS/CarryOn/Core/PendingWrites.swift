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
    public func hasPending(scope: String, target: String) -> Bool {
        let prefix = hash(scope + "\n" + target)
        return entries.keys.contains { $0 == prefix || $0.hasPrefix(prefix + ":") }
    }
    public func requestIDs(scope: String, target: String) throws -> Set<String> {
        guard !unreadable else { throw APIError("本地请求记录无法读取，请保留 App 数据并核对原请求。") }
        let prefix = hash(scope + "\n" + target)
        return Set(entries.filter { $0.key == prefix || $0.key.hasPrefix(prefix + ":") }.values.map(\.requestID))
    }
    public func existingRequestID(scope: String, target: String, path: String, body: JSONValue) throws -> String? {
        guard !unreadable else { throw APIError("本地请求记录无法读取，已暂停写入，请保留 App 数据并核对原请求。") }
        let prefix = hash(scope + "\n" + target)
        let digest = hash(path + "\n" + String(decoding: try body.encoded(), as: UTF8.self))
        return entries[prefix + ":" + digest]?.requestID ?? entries[prefix].flatMap { $0.digest == digest ? $0.requestID : nil }
    }
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
        try reconcile(scope: scope, jobs: [job])
    }
    public func reconcile(scope: String, jobs: [JSONValue]) throws {
        guard !entries.isEmpty else { return }
        let requestIDs = Set(entries.values.map(\.requestID))
        var changed = false
        for job in jobs where requestIDs.contains(job["id"].text) {
            guard ["accepted", "completed", "inProgress", "acknowledged", "failed", "interrupted"].contains(job["state"].text) else { continue }
            if ["plugin-install", "plugin-uninstall"].contains(job["kind"].text) {
                guard let receipt = try? PluginReceipt(job),
                      try existingRequestID(scope: scope, target: "plugin-management", path: receipt.path, body: receipt.body) == job["id"].text,
                      !["accepted", "completed", "inProgress"].contains(job["state"].text) || receipt.completed else { continue }
                if remove(scope: scope, target: "plugin-management", requestID: job["id"].text) { changed = true }
                continue
            }
            if job["kind"].text == "skill-config" {
                guard let receipt = try? SkillConfigurationReceipt(job),
                      try existingRequestID(scope: scope, target: "skill-config", path: receipt.path, body: receipt.body) == job["id"].text,
                      !["accepted", "completed", "inProgress"].contains(job["state"].text) || receipt.completed else { continue }
                if remove(scope: scope, target: "skill-config", requestID: job["id"].text) { changed = true }
                continue
            }
            if ["terminal-terminate", "terminal-clean"].contains(job["kind"].text) {
                guard let receipt = try? TerminalReceipt(job),
                      try existingRequestID(scope: scope, target: "terminal:" + receipt.threadID, path: receipt.path, body: receipt.body) == job["id"].text,
                      !["accepted", "completed", "inProgress"].contains(job["state"].text) || receipt.completed else { continue }
                if remove(scope: scope, target: "terminal:" + receipt.threadID, requestID: job["id"].text) { changed = true }
                continue
            }
            if ["section-create", "section-update", "section-delete", "section-order"].contains(job["kind"].text) {
                guard let receipt = try? SectionReceipt(job),
                      try existingRequestID(scope: scope, target: "sections", path: receipt.path, body: receipt.body) == job["id"].text,
                      !["accepted", "completed", "inProgress"].contains(job["state"].text) || receipt.completed else { continue }
                if remove(scope: scope, target: "sections", requestID: job["id"].text) { changed = true }
                continue
            }
            if job["kind"].text == "rename" {
                guard let name = job["name"].string,
                      try existingRequestID(scope: scope, target: job["threadId"].text,
                        path: "/api/threads/" + ConsoleAddress.component(job["threadId"].text) + "/rename",
                        body: .object(["name": .string(name)])) == job["id"].text else { continue }
            }
            if job["kind"].text == "section-move" {
                guard job.object?.keys.contains("sectionId") == true,
                      job["sectionId"] == .null || job["sectionId"].string != nil,
                      try existingRequestID(scope: scope, target: job["threadId"].text,
                        path: "/api/threads/" + ConsoleAddress.component(job["threadId"].text) + "/section",
                        body: .object(["sectionId": job["sectionId"]])) == job["id"].text else { continue }
                if ["accepted", "completed", "inProgress"].contains(job["state"].text),
                   job["state"].text != "completed" || job["result"]["threadId"].text != job["threadId"].text ||
                    job["result"].object?.keys.contains("sectionId") != true || job["result"]["sectionId"] != job["sectionId"] { continue }
            }
            if job["kind"].text == "create", ["accepted", "completed", "inProgress"].contains(job["state"].text), job["createdThreadId"].string?.isEmpty != false { continue }
            if ["archive", "unarchive"].contains(job["kind"].text), ["accepted", "completed", "inProgress"].contains(job["state"].text),
               job["state"].text != "completed" || job["result"]["threadId"].text != job["threadId"].text ||
                job["result"]["archived"].bool != (job["kind"].text == "archive") { continue }
            if job["kind"].text == "rename", ["accepted", "completed", "inProgress"].contains(job["state"].text),
               job["state"].text != "completed" || job["result"]["threadId"].text != job["threadId"].text ||
                job["result"]["name"].string == nil || job["result"]["name"] != job["name"] { continue }
            var targets = [job["threadId"].text, "new"]
            if let project = job["creationProject"]["groupId"].string { targets.append("new:" + project) }
            for target in targets {
                if remove(scope: scope, target: target, requestID: job["id"].text) { changed = true }
            }
        }
        if changed { try save() }
    }
    public func resolve(scope: String, target: String, requestID: String) throws {
        if remove(scope: scope, target: target, requestID: requestID) { try save() }
    }
    private func remove(scope: String, target: String, requestID: String) -> Bool {
        guard entries.values.contains(where: { $0.requestID == requestID }) else { return false }
        let count = entries.count
        let prefix = hash(scope + "\n" + target)
        entries = entries.filter { key, entry in
            !((key == prefix || key.hasPrefix(prefix + ":")) && entry.requestID == requestID)
        }
        return entries.count != count
    }
    private func save() throws { defaults.set(try JSONEncoder().encode(entries), forKey: storageKey) }
}
