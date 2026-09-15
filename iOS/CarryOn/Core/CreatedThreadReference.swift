import Foundation

public enum CreatedThreadReference {
    private static let pattern = #"(?m)^::created-thread\{(threadId|clientThreadId)=\"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\"\}[ \t]*$"#
    public static func threadIDs(in text: String) -> [String] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        var ids: [String] = []
        for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
            guard let kind = Range(match.range(at: 1), in: text), text[kind] == "threadId",
                  let range = Range(match.range(at: 2), in: text) else { continue }
            let id = String(text[range])
            if !ids.contains(id) { ids.append(id) }
        }
        return ids
    }
    public static func render(_ text: String, titles: [String: String]) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return text }
        var result = text
        for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
            guard let range = Range(match.range, in: result), let kind = Range(match.range(at: 1), in: text),
                  let idRange = Range(match.range(at: 2), in: text) else { continue }
            let id = String(text[idRange])
            if text[kind] == "clientThreadId" { result.replaceSubrange(range, with: "会话创建中"); continue }
            let title = titles[id] ?? "新会话"
            let escaped = title.reduce(into: "") { value, character in
                if "\\`*_{}[]()<>!#|".contains(character) { value.append("\\") }
                value.append(character.isNewline ? " " : character)
            }
            result.replaceSubrange(range, with: "[" + escaped + "](carryon-thread:" + id + ")")
        }
        return result
    }
}
