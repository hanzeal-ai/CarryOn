import Testing
@testable import CarryOnCore

private let createdID = "01a09ffc-f7ec-7eb1-b97f-81f8ca0456ef"
@Test func completedCreatedThreadDirectiveRendersResolvedClickableTitle() {
    let text = "已新建任务。\n\n::created-thread{threadId=\"\(createdID)\"}\n\n完成。"
    #expect(CreatedThreadReference.threadIDs(in: text) == [createdID])
    #expect(CreatedThreadReference.render(text, titles: [createdID: "回复 hello"]) == "已新建任务。\n\n[回复 hello](carryon-thread:\(createdID))\n\n完成。")
    #expect(CreatedThreadReference.render(text, titles: [:]).contains("[新会话](carryon-thread:"))
}
@Test func pendingAndMalformedThreadReferencesNeverBecomeNavigationTargets() {
    let pending = "::created-thread{clientThreadId=\"\(createdID)\"}"
    #expect(CreatedThreadReference.threadIDs(in: pending).isEmpty)
    #expect(CreatedThreadReference.render(pending, titles: [:]) == "会话创建中")
    for text in ["::created-thread{threadId=\"invalid\"}", "::created-thread{threadId=\"\(createdID)", "Example ::created-thread{threadId=\"\(createdID)\"}"] {
        #expect(CreatedThreadReference.threadIDs(in: text).isEmpty)
        #expect(CreatedThreadReference.render(text, titles: [:]) == text)
    }
}
@Test func createdThreadTitlesCannotInjectMarkdownLinks() {
    let text = "::created-thread{threadId=\"\(createdID)\"}"
    let rendered = CreatedThreadReference.render(text, titles: [createdID: "[标题](https://example.com)\n下一行"])
    #expect(rendered.contains("\\[标题\\]\\(https://example.com\\) 下一行"))
    #expect(CreatedThreadReference.threadIDs(in: text + "\n" + text) == [createdID])
}
