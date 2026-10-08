import Foundation

/// A one-character attachment occupies a UTF-16 position in the stored draft.
/// Native input identities remain name/path; offsets are editor-only metadata.
public struct ComposerDocument: Equatable, Sendable {
    public static let marker = "\u{fffc}"
    public var text: String
    public var skills: [ComposerReference]
    public init(text: String, skills: [ComposerReference]) {
        self.text = text; self.skills = []
        var occupied = Set<Int>()
        for skill in skills {
            if let offset = skill.offset, offset >= 0, offset < (text as NSString).length,
               (text as NSString).substring(with: NSRange(location: offset, length: 1)) == Self.marker,
               occupied.insert(offset).inserted {
                self.skills.append(skill)
            } else {
                let offset = (self.text as NSString).length
                self.text += Self.marker
                self.skills.append(.init(name: skill.name, path: skill.path, offset: offset, displayName: skill.displayName, iconData: skill.iconData))
                occupied.insert(offset)
            }
        }
    }
    public var wireText: String { text.replacingOccurrences(of: Self.marker, with: "") }
    public var displayText: String {
        let result = NSMutableString(string: text)
        for skill in skills.sorted(by: { ($0.offset ?? 0) > ($1.offset ?? 0) }) {
            if let offset = skill.offset { result.replaceCharacters(in: NSRange(location: offset, length: 1), with: skill.label) }
        }
        return result as String
    }
    public mutating func replace(_ range: NSRange, with replacement: String) {
        guard range.location >= 0, range.length >= 0, range.location <= (text as NSString).length,
              range.length <= (text as NSString).length - range.location else { return }
        let clean = replacement.replacingOccurrences(of: Self.marker, with: "")
        let delta = (clean as NSString).length - range.length
        skills = skills.compactMap { skill in
            guard let offset = skill.offset else { return nil }
            if NSLocationInRange(offset, range) { return nil }
            return .init(name: skill.name, path: skill.path, offset: offset >= NSMaxRange(range) ? offset + delta : offset, displayName: skill.displayName, iconData: skill.iconData)
        }
        text = (text as NSString).replacingCharacters(in: range, with: clean)
    }
    public mutating func insert(_ skill: ComposerReference, at position: Int) {
        let offset = min(max(0, position), (text as NSString).length)
        skills = skills.map { reference in
            .init(name: reference.name, path: reference.path, offset: (reference.offset ?? 0) >= offset ? (reference.offset ?? 0) + 1 : reference.offset, displayName: reference.displayName, iconData: reference.iconData)
        }
        text = (text as NSString).replacingCharacters(in: NSRange(location: offset, length: 0), with: Self.marker)
        skills.append(.init(name: skill.name, path: skill.path, offset: offset, displayName: skill.displayName, iconData: skill.iconData))
    }
    public mutating func remove(_ skill: ComposerReference) {
        let matches = skills.filter { $0.name == skill.name && $0.path == skill.path }.sorted { ($0.offset ?? 0) > ($1.offset ?? 0) }
        for match in matches { if let offset = match.offset { replace(NSRange(location: offset, length: 1), with: "") } }
    }
}
