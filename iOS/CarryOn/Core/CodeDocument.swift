import Foundation

/// Presentation metadata only; attachment access remains scoped by the server.
public struct CodeDocument: Identifiable, Sendable {
    public let id: String
    public let name: String
    public let text: String
    public let language: String
    public var isMarkdown: Bool { language == "markdown" }
    public static let highlightLimit = 100_000

    public init?(name: String, data: Data) {
        guard let language = Self.language(filename: name),
              let text = String(data: data, encoding: .utf8), !text.contains("\0") else { return nil }
        self.id = UUID().uuidString
        self.name = name
        self.text = text
        self.language = language
    }

    public static func language(filename: String) -> String? {
        let name = (filename as NSString).lastPathComponent.lowercased()
        if name == "dockerfile" { return "dockerfile" }
        if name == "makefile" { return "makefile" }
        let ext = (name as NSString).pathExtension
        return ["swift": "swift", "py": "python", "js": "javascript", "jsx": "javascript",
                "ts": "typescript", "tsx": "typescript", "json": "json", "go": "go", "rs": "rust",
                "java": "java", "kt": "kotlin", "kts": "kotlin", "c": "c", "h": "c",
                "cpp": "cpp", "cc": "cpp", "hpp": "cpp", "m": "objectivec", "mm": "objectivec",
                "cs": "csharp", "rb": "ruby", "php": "php", "sh": "bash", "zsh": "bash",
                "bash": "bash", "sql": "sql", "html": "xml", "xml": "xml", "svg": "xml",
                "css": "css", "scss": "scss", "yaml": "yaml", "yml": "yaml", "toml": "ini",
                "ini": "ini", "md": "markdown", "markdown": "markdown", "txt": "plaintext",
                "log": "plaintext", "diff": "diff", "patch": "diff", "vue": "xml",
                "dart": "dart", "r": "r", "lua": "lua", "pl": "perl"][ext]
    }

    public static func normalizedLanguage(_ info: String?) -> String {
        let token = info?.split(whereSeparator: { $0.isWhitespace }).first.map(String.init)?.lowercased() ?? ""
        return ["js": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript",
                "py": "python", "sh": "bash", "shell": "bash", "yml": "yaml", "html": "xml",
                "text": "plaintext", "": "plaintext"][token] ?? token
    }
}
