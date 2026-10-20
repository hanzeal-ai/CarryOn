import Foundation
import CryptoKit

/// Local authoring data. Native execution receives its deterministic text projection.
public struct ReviewComment: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let sourceID: String
    public let patchID: String
    public let path: String
    public let lineID: Int
    public let location: String
    public let lineText: String
    public var text: String
    public init?(sourceID: String, path: String, patch: String, line: UnifiedDiff.Line, text: String) {
        guard let location = line.location, !sourceID.isEmpty, !path.isEmpty,
              UnifiedDiff.lines(patch).contains(line), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        id = UUID().uuidString; self.sourceID = sourceID; patchID = Self.patchIdentity(patch)
        self.path = path; lineID = line.id; self.location = location; lineText = line.text; self.text = text
    }
    public static func patchIdentity(_ patch: String) -> String {
        SHA256.hash(data: Data(patch.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    public var prompt: String { "关于已加载改动 \(path)（\(location)）：\n\(lineText)\n\(text)" }
}

public struct ConversationDraft: Codable, Equatable, Sendable {
    public var text: String
    public var images: [String]
    public var skills: [ComposerReference]
    public var comments: [ReviewComment]
    public var files: [ProjectFileReference]?
    public var uploads: [ConversationUpload]?
    public init(text: String = "", images: [String] = [], skills: [ComposerReference] = [], comments: [ReviewComment] = [], files: [ProjectFileReference] = [], uploads: [ConversationUpload] = []) {
        self.text = text; self.images = images; self.skills = skills; self.comments = comments
        self.files = files.isEmpty ? nil : files
        self.uploads = uploads.isEmpty ? nil : uploads
    }
    public var prompt: String {
        ([text] + comments.map(\.prompt)).filter { !$0.isEmpty }.joined(separator: "\n\n")
    }
    /// Clear only the content submitted, preserving edits made while awaiting a reply.
    public mutating func didSubmit(_ sent: ConversationDraft) {
        if text == sent.text { text = "" }
        if images == sent.images { images = [] }
        if skills == sent.skills { skills = [] }
        if files == sent.files { files = nil }
        uploads?.removeAll { current in sent.uploads?.contains(current) == true }
        if uploads?.isEmpty == true { uploads = nil }
        comments.removeAll { current in sent.comments.contains(current) }
    }
}

public enum ComposerAction: Equatable, Sendable {
    case send, pause, restart, unavailable
    public static func resolve(text: String, hasImages: Bool, running: Bool, interrupted: Bool) -> Self {
        if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || hasImages { return .send }
        if running { return .pause }
        return interrupted ? .restart : .unavailable
    }
}

public struct DraftSubmission: Codable, Equatable, Sendable {
    public let scope: String
    public let threadID: String
    public let draft: ConversationDraft
    public let draftKey: String?
    public let creation: Bool?
    public init(scope: String, threadID: String, draft: ConversationDraft, draftKey: String? = nil, creation: Bool = false) {
        self.scope = scope; self.threadID = threadID; self.draft = draft; self.draftKey = draftKey; self.creation = creation ? true : nil
    }
}
