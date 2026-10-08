import Testing
@testable import CarryOnCore

@Test func composerCommandsPreserveArgumentsAndFilePaths() {
    #expect(ComposerCommand(" /goal  完成改造\n并审查 ") == ComposerCommand("/goal 完成改造\n并审查"))
    #expect(ComposerCommand("/side\t讨论边界")?.argument == "讨论边界")
    #expect(ComposerCommand("/compact")?.operation == "compact")
    #expect(ComposerCommand("/plan")?.capability == .edit)
    #expect(ComposerCommand("/unknown")?.name == "unknown")
    #expect(ComposerCommand("/usr/local") == nil)
    #expect(ComposerCommand("普通文本 /review") == nil)
    #expect(ComposerCommand.query("/pl") == "pl")
    #expect(ComposerCommand.query("/plan 任务") == nil)
}
