import Foundation
import CryptoKit
import Darwin

public enum UploadKind: String, Codable, Sendable { case file, directory }

public struct UploadTarget: Codable, Equatable, Sendable {
    public let type: String
    public let threadID: String?
    public let projectID: String?
    public static func thread(_ id: String) -> Self { .init(type: "thread", threadID: id, projectID: nil) }
    public static func creation(_ projectID: String?) -> Self { .init(type: "creation", threadID: nil, projectID: projectID) }
    public var value: JSONValue {
        if type == "thread" { return .object(["type": .string(type), "threadId": .string(threadID ?? "")]) }
        var fields: [String: JSONValue] = ["type": .string(type)]
        if let projectID { fields["projectId"] = .string(projectID) }
        return .object(fields)
    }
    public func matches(_ value: JSONValue) -> Bool {
        guard value["type"].string == type else { return false }
        if type == "thread" { return threadID?.isEmpty == false && value["threadId"].string == threadID }
        guard type == "creation" else { return false }
        return projectID.map { value["projectId"].string == $0 } ?? (value["projectId"] == .null)
    }
}

public struct UploadLimits: Sendable {
    public let chunkBytes: Int
    public let maxEntries: Int
    public let maxFileBytes: Int
    public let maxTotalBytes: Int
    public init?(value: JSONValue) {
        guard let chunk = value["chunkBytes"].int, (1...49_152).contains(chunk),
              let entries = value["maxEntries"].int, entries > 0,
              let file = value["maxFileBytes"].int, file > 0,
              let total = value["maxTotalBytes"].int, total > 0 else { return nil }
        chunkBytes = chunk; maxEntries = entries; maxFileBytes = file; maxTotalBytes = total
    }
}

public struct UploadEntry: Codable, Equatable, Sendable {
    public let path: String
    public let kind: UploadKind
    public let size: Int?
    public let sha256: String?
    public var value: JSONValue {
        var fields: [String: JSONValue] = ["path": .string(path), "kind": .string(kind.rawValue)]
        if let size { fields["size"] = .number(Double(size)) }
        if let sha256 { fields["sha256"] = .string(sha256) }
        return .object(fields)
    }
}

/// A local immutable snapshot and its target-bound server receipt. Paths are never sent as references.
public struct ConversationUpload: Codable, Equatable, Identifiable, Sendable {
    public static let maximumReferences = 20
    public let id: String
    public let name: String
    public let kind: UploadKind
    public let target: UploadTarget
    public let entries: [UploadEntry]
    public var uploadID: String?
    public var failure: String?
    public var complete: Bool { uploadID?.isEmpty == false }
    public var size: Int { entries.reduce(0) { $0 + ($1.size ?? 0) } }
    public init(id: String = UUID().uuidString, name: String, kind: UploadKind, target: UploadTarget, entries: [UploadEntry], uploadID: String? = nil, failure: String? = nil) {
        self.id = id; self.name = name; self.kind = kind; self.target = target; self.entries = entries
        self.uploadID = uploadID; self.failure = failure
    }
}

public enum UploadStaging {
    private static var directory: URL { LocalFiles.directory.appendingPathComponent("Uploads", isDirectory: true) }
    public static func root(for id: String) throws -> URL {
        guard UUID(uuidString: id) != nil else { throw APIError("附件标识无效") }
        return directory.appendingPathComponent(id, isDirectory: true)
    }
    public static func remove(_ upload: ConversationUpload) {
        if let root = try? root(for: upload.id) { try? FileManager.default.removeItem(at: root) }
    }
    private static func validName(_ name: String) -> Bool {
        !name.isEmpty && name != "." && name != ".." && !name.contains("/") && !name.contains("\\")
            && !name.unicodeScalars.contains { CharacterSet.controlCharacters.contains($0) }
    }
    /// Descriptor-relative traversal refuses symlinks, including replacements during enumeration.
    public static func prepare(url: URL, kind: UploadKind, target: UploadTarget, limits: UploadLimits) throws -> ConversationUpload {
        guard url.isFileURL, validName(url.lastPathComponent) else { throw APIError("文件名无效") }
        let name = url.lastPathComponent.precomposedStringWithCanonicalMapping
        let id = UUID().uuidString, root = try root(for: id), manager = FileManager.default
        try manager.createDirectory(at: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        var excluded = root, resources = URLResourceValues(); resources.isExcludedFromBackup = true
        try excluded.setResourceValues(resources)
        var entries: [UploadEntry] = [], total = 0
        func visit(_ descriptor: Int32, path: String) throws {
            try Task.checkCancellation()
            var info = stat()
            guard fstat(descriptor, &info) == 0 else { throw APIError("无法读取文件信息") }
            let type = info.st_mode & S_IFMT
            guard type == S_IFDIR || type == S_IFREG else { throw APIError("不支持符号链接或特殊文件：\(path)") }
            guard entries.count < limits.maxEntries else { throw APIError("附件最多包含 \(limits.maxEntries) 个文件或目录") }
            let destination = root.appendingPathComponent(path)
            if type == S_IFDIR {
                entries.append(.init(path: path, kind: .directory, size: nil, sha256: nil))
                try manager.createDirectory(at: destination, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
                let duplicate = dup(descriptor)
                guard duplicate >= 0 else { throw APIError("目录无法读取：\(path)") }
                guard let listing = fdopendir(duplicate) else { close(duplicate); throw APIError("目录无法读取：\(path)") }
                defer { closedir(listing) }
                var names: [String] = []
                errno = 0
                while let entry = readdir(listing) {
                    let name = withUnsafePointer(to: &entry.pointee.d_name) {
                        $0.withMemoryRebound(to: CChar.self, capacity: Int(entry.pointee.d_namlen) + 1) { String(cString: $0) }
                    }
                    if name != "." && name != ".." {
                        guard names.count < limits.maxEntries - entries.count else { throw APIError("附件最多包含 \(limits.maxEntries) 个文件或目录") }
                        names.append(name)
                    }
                }
                guard errno == 0 else { throw APIError("目录读取失败：\(path)") }
                var normalizedNames = Set<String>()
                for name in names.sorted() {
                    let normalized = name.precomposedStringWithCanonicalMapping
                    guard normalizedNames.insert(normalized).inserted else { throw APIError("文件名规范化后重复：\(name)") }
                    guard validName(name) else { throw APIError("文件名无效：\(name)") }
                    let child = openat(descriptor, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
                    guard child >= 0 else { throw APIError("无法读取文件或不支持符号链接：\(path)/\(name)") }
                    defer { close(child) }
                    try visit(child, path: path + "/" + normalized)
                }
            } else {
                guard info.st_size >= 0, info.st_size <= limits.maxFileBytes,
                      info.st_size <= limits.maxTotalBytes - total else { throw APIError("附件大小超过工作区限制：\(path)") }
                guard manager.createFile(atPath: destination.path, contents: nil, attributes: [.posixPermissions: 0o600]) else { throw APIError("无法暂存附件") }
                #if os(iOS)
                try manager.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: destination.path)
                #endif
                let input = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
                let output = try FileHandle(forWritingTo: destination); defer { try? output.close() }
                var digest = SHA256(), count = 0
                while let data = try input.read(upToCount: limits.chunkBytes), !data.isEmpty {
                    try Task.checkCancellation()
                    guard data.count <= limits.maxFileBytes - count, data.count <= limits.maxTotalBytes - total else { throw APIError("附件大小超过工作区限制：\(path)") }
                    try output.write(contentsOf: data); digest.update(data: data); count += data.count; total += data.count
                }
                guard count == info.st_size else { throw APIError("文件在读取时发生变化，请重新选择：\(path)") }
                entries.append(.init(path: path, kind: .file, size: count, sha256: digest.finalize().map { String(format: "%02x", $0) }.joined()))
            }
        }
        do {
            let source = open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
            guard source >= 0 else { throw APIError("无法读取附件或不支持符号链接") }
            defer { close(source) }
            var info = stat()
            guard fstat(source, &info) == 0, (info.st_mode & S_IFMT) == (kind == .directory ? S_IFDIR : S_IFREG) else { throw APIError("请选择\(kind == .directory ? "文件夹" : "普通文件")") }
            try visit(source, path: name)
            return .init(id: id, name: name, kind: kind, target: target, entries: entries)
        } catch { try? manager.removeItem(at: root); throw error }
    }
    public static func chunk(_ upload: ConversationUpload, entry: UploadEntry, offset: Int, count: Int) throws -> Data {
        let parts = entry.path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard parts.first == upload.name, parts.allSatisfy(validName), offset >= 0, count > 0 else { throw APIError("附件路径无效") }
        let url = try root(for: upload.id).appendingPathComponent(entry.path)
        let file = try FileHandle(forReadingFrom: url); defer { try? file.close() }
        try file.seek(toOffset: UInt64(offset))
        return try file.read(upToCount: count) ?? Data()
    }
}

public enum UploadTransfer {
    @MainActor public static func send(_ upload: ConversationUpload, limits: UploadLimits,
        request: (String, JSONValue?) async throws -> JSONValue, progress: (Int) -> Void = { _ in }) async throws -> String {
        let response = try await request("/api/uploads", .object(["action": .string("begin"),
            "requestId": .string(upload.id), "name": .string(upload.name), "kind": .string(upload.kind.rawValue),
            "target": upload.target.value, "entries": .array(upload.entries.map(\.value))]))
        func receipt(_ value: JSONValue, id: String? = nil) throws -> String {
            guard let identifier = value["id"].string, identifier.utf8.count == 32,
                  identifier.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
                  id == nil || identifier == id,
                  value["name"].string == upload.name, value["kind"].string == upload.kind.rawValue,
                  upload.target.matches(value["target"]) else { throw APIError("上传回执身份不匹配，请重试") }
            return identifier
        }
        let id = try receipt(response)
        if response["state"].text == "complete" { return id }
        guard response["state"].text == "uploading" else { throw APIError("上传状态未确认，请重试") }
        var sent = 0
        for entry in upload.entries where entry.kind == .file {
            var offset = 0
            while offset < (entry.size ?? 0) {
                try Task.checkCancellation()
                let position = offset
                let data = try await Task.detached(priority: .utility) { try UploadStaging.chunk(upload, entry: entry, offset: position, count: limits.chunkBytes) }.value
                guard !data.isEmpty, data.count <= (entry.size ?? 0) - offset else { throw APIError("暂存附件发生变化，请移除后重新选择") }
                let result = try await request("/api/uploads", .object(["action": .string("chunk"), "uploadId": .string(id),
                    "path": .string(entry.path), "offset": .number(Double(offset)), "data": .string(data.base64EncodedString())]))
                guard result["offset"].int == offset + data.count else { throw APIError("上传进度未确认，请重试") }
                offset += data.count; sent += data.count; progress(sent)
            }
        }
        let result = try await request("/api/uploads", .object(["action": .string("complete"), "uploadId": .string(id)]))
        guard result["state"].text == "complete" else { throw APIError("上传尚未完成，请重试") }
        return try receipt(result, id: id)
    }
}
