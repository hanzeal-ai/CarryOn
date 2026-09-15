import Testing
@testable import CarryOnCore

private func entry(_ id: String, _ type: String, phase: String? = nil, turn: String = "a") -> JSONValue {
    var fields: [String: JSONValue] = ["id": .string(id), "type": .string(type), "turnId": .string(turn)]
    if let phase { fields["phase"] = .string(phase) }
    return .object(fields)
}

@Test func textOutputSeparatesIndependentlyScrollableExecutionStages() {
    let turn = entry("turn", "turn").setting("status", .string("completed")).setting("data", .object(["durationMs": .number(81000)]))
    let rows = ConversationProcess.timeline([turn, entry("user", "userMessage"), entry("command", "commandExecution"), entry("progress", "agentMessage", phase: "commentary"), entry("agent", "subAgentActivity"), entry("final", "agentMessage", phase: "final_answer")])
    #expect(rows.map { $0["type"].text } == ["userMessage", "processGroup", "agentMessage", "processGroup", "agentMessage"])
    #expect(rows[1]["items"].array.map { $0["id"].text } == ["command"])
    #expect(rows[2]["id"].text == "progress")
    #expect(rows[3]["items"].array.map { $0["id"].text } == ["agent"])
    #expect(rows[1]["data"]["durationMs"] == .null)
    #expect(rows[3]["data"]["durationMs"] == .null)
    #expect(rows.last?["id"].text == "final")
}

@Test func questionsErrorsAndUnclassifiedAnswersStayVisible() {
    let question = entry("question", "agentMessage", phase: "commentary").setting("asyncQuestions", .array([.object(["active": .bool(true)])]))
    let rows = ConversationProcess.timeline([entry("turn", "turn"), entry("command", "commandExecution"), question, entry("error", "error"), entry("legacy", "agentMessage")])
    #expect(rows.map { $0["id"].text } == ["command:process", "question", "error", "legacy"])
    #expect(ConversationProcess.summary(rows[0]) == "运行命令")
}

@Test func processNeverCrossesTurnsAndIdentitySurvivesCompletion() {
    let active = entry("turn", "turn").setting("status", .string("inProgress"))
    let command = entry("cmd", "commandExecution").setting("data", .object(["command": .string("swift test")]))
    let running = ConversationProcess.timeline([active, command])
    let done = ConversationProcess.timeline([active.setting("status", .string("completed")), command, entry("turn2", "turn", turn: "b"), entry("cmd2", "commandExecution", turn: "b")])
    #expect(running[0]["id"] == done[0]["id"])
    #expect(done.count == 2)
    #expect(ConversationProcess.summary(running[0]) == "运行 swift test")
}

@Test func expandedProcessShowsConcreteActivitiesWithoutRepeatedReasoning() {
    let command = entry("cmd", "commandExecution")
    let file = entry("file", "fileChange")
    let commentary = entry("progress", "agentMessage", phase: "commentary")
    let reasoning = entry("think", "reasoning").setting("text", .string("**Checking tests**"))
    let failed = command.setting("id", .string("failed")).setting("status", .string("failed"))
    let group: JSONValue = .object(["items": .array([command, reasoning, file, commentary, failed])])
    #expect(ConversationProcess.bodyItems(group) == [command, file, commentary, failed])
}

@Test func currentActionPrefersLiveCommandOverLaterProgressMessage() {
    let command = entry("cmd", "commandExecution").setting("status", .string("inProgress")).setting("data", .object(["command": .string("swift test")]))
    let progress = entry("progress", "agentMessage", phase: "commentary").setting("text", .string("正在核对"))
    let group: JSONValue = .object(["active": .bool(true), "items": .array([command, progress])])
    #expect(ConversationProcess.summary(group) == "运行 swift test")
    let reasoning = entry("reason", "reasoning").setting("status", .string("inProgress")).setting("text", .string("**Checking results**"))
    #expect(String(ConversationProcess.summaryLabel(group.setting("items", .array([command.setting("status", .string("completed")), reasoning, progress]))).characters) == "Checking results")
}

@Test func streamingFinalEndsTheActivitySummaryWithoutFakingTurnCompletion() {
    let turn = entry("turn", "turn").setting("status", .string("inProgress"))
    let rows = ConversationProcess.timeline([turn, entry("cmd", "commandExecution"), entry("final", "agentMessage", phase: "final_answer")])
    #expect(rows[0]["active"] == .bool(false))
    #expect(rows[0]["status"] == .string("inProgress"))
    #expect(rows[1]["id"].text == "final")
}

@Test func generatedImagesRemainInlineOutsideCollapsedProcess() {
    let image = entry("image", "mcpToolCall").setting("artifacts", .array([.object(["kind": .string("image"), "id": .string("artifact")])]))
    let rows = ConversationProcess.timeline([entry("turn", "turn"), entry("cmd", "commandExecution"), image])
    #expect(rows.count == 2)
    #expect(rows[1] == image)
}

@Test func processSummaryRendersMarkdownButKeepsCommandSyntaxLiteral() {
    let reasoning = entry("reason", "reasoning").setting("text", .string("**Formatting new JSX openings**"))
    let group: JSONValue = .object(["active": .bool(true), "items": .array([reasoning])])
    let label = ConversationProcess.summaryLabel(group)
    #expect(String(label.characters) == "Formatting new JSX openings")
    #expect(label.runs.contains { $0.inlinePresentationIntent?.contains(.stronglyEmphasized) == true })
    let command = entry("cmd", "commandExecution").setting("data", .object(["command": .string("ls **/*.swift")]))
    #expect(String(ConversationProcess.summaryLabel(group.setting("items", .array([command]))).characters) == "运行 ls **/*.swift")
}

@Test func newStageOwnsCurrentActionAfterProgressText() {
    let turn = entry("turn", "turn").setting("status", .string("inProgress"))
    let first = entry("cmd1", "commandExecution").setting("status", .string("completed"))
    let progress = entry("progress", "agentMessage", phase: "commentary")
    let second = entry("cmd2", "commandExecution").setting("status", .string("inProgress")).setting("data", .object(["command": .string("swift test")]))
    let rows = ConversationProcess.timeline([turn, first, progress, second])
    #expect(rows.map { $0["type"].text } == ["processGroup", "agentMessage", "processGroup"])
    #expect(rows[0]["active"] == .bool(false))
    #expect(rows[2]["active"] == .bool(true))
    #expect(rows[0]["id"] != rows[2]["id"])
    #expect(ConversationProcess.summary(rows[2]) == "运行 swift test")
}

@Test func singleCallHasNoDuplicateStageHeaderAndMultipleCallsHaveReadableSummary() {
    let command = entry("cmd", "commandExecution")
    let group: JSONValue = .object(["items": .array([command])])
    #expect(ConversationProcess.singleActivity(group) == command)
    let multiple = group.setting("items", .array([command, entry("file", "fileChange")]))
    #expect(ConversationProcess.singleActivity(multiple) == nil)
    #expect(ConversationProcess.summary(multiple) == "运行命令、修改文件")
    #expect(ConversationProcess.singleActivity(group.setting("items", .array([entry("reason", "reasoning")]))) == nil)
}
