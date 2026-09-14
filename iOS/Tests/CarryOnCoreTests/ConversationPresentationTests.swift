import Testing
@testable import CarryOnCore

@Test func artifactReferencesBecomeInlineLinksWithoutRepeatingOrOpeningUnknownPaths() {
    let item: JSONValue = .object([
        "text": .string("![图片](</tmp/my image.png>) [源码](/tmp/a.swift:12) [外链](https://example.com)"),
        "artifacts": .array([
            .object(["id": .string("image"), "name": .string("my image.png"), "path": .string("/tmp/my image.png")]),
            .object(["id": .string("code"), "name": .string("a.swift"), "path": .string("/tmp/a.swift")]),
            .object(["id": .string("unused"), "name": .string("other.png"), "path": .string("/tmp/other.png")])
        ])
    ])
    let text = ConversationPresentation.attachmentDisplayText(item)
    #expect(text == "[my image.png](carryon-artifact:image) [a.swift](carryon-artifact:code) [外链](https://example.com)")
    #expect(ConversationPresentation.referencedArtifactIDs(item) == ["image", "code"])
}

@Test func activityShowsContentAndDoesNotExpandEmptyLifecycleMetadata() {
    let command: JSONValue = .object(["type": .string("commandExecution"), "title": .string("执行命令"), "text": .string("swift test"), "data": .object(["command": .string("swift test")])])
    #expect(ConversationPresentation.activityText(command) == "swift test")
    #expect(ConversationPresentation.hasActivityDetails(command))
    #expect(!ConversationPresentation.hasActivityDetails(.object(["data": .object(["status": .string("completed"), "summary": .array([])])])))
    #expect(ConversationPresentation.activityText(.object(["data": .object(["query": .string("Swift UI rendering")])])) == "Swift UI rendering")
}

@Test func activityMarkdownRendersBoldButPreservesShellGlobs() {
    let reasoning: JSONValue = .object(["type": .string("reasoning"), "text": .string("**检查图片预览**并修复")])
    let label = ConversationPresentation.activityLabel(reasoning)
    #expect(String(label.characters) == "检查图片预览并修复")
    #expect(label.runs.contains { $0.inlinePresentationIntent?.contains(.stronglyEmphasized) == true })
    let command: JSONValue = .object(["type": .string("commandExecution"), "text": .string("ls **/*.swift")])
    #expect(String(ConversationPresentation.activityLabel(command).characters) == "ls **/*.swift")
}
