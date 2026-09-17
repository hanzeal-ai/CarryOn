import Testing
@testable import CarryOnCore

private func activityHistory(status: String = "completed", items: [JSONValue], requests: [JSONValue] = []) -> JSONValue {
    .object(["thread": .object(["id": .string("thread")]),
             "timeline": .array([.object(["id": .string("turn:turn"), "type": .string("turn"), "turnId": .string("turn"), "status": .string(status), "data": .object(["completedAt": .number(123)])])] + items),
             "controls": .object(["requests": .array(requests)])])
}
private func activityMessage(_ id: String, phase: String, text: String) -> JSONValue {
    .object(["id": .string(id), "type": .string("agentMessage"), "turnId": .string("turn"), "phase": .string(phase), "text": .string(text)])
}
@Test func activityShowsOnlyFinalResult() {
    let detail = ActivityDetail(history: activityHistory(items: [
        activityMessage("progress", phase: "commentary", text: "正在修改"),
        activityMessage("final", phase: "final", text: "修改结果"),
        activityMessage("later-progress", phase: "commentary", text: "工具状态")
    ]))
    #expect(detail.kind == .completed)
    #expect(detail.result["text"].text == "修改结果")
    #expect(detail.anchorID == "final")
    #expect(detail.completedAt == 123)
}
@Test func activityDoesNotPresentIntermediateMessageAsResult() {
    let detail = ActivityDetail(history: activityHistory(items: [activityMessage("progress", phase: "commentary", text: "处理中")]))
    #expect(detail.result == .null)
}
@Test func activityShowsFailureReasonWithoutPreviousSuccess() {
    let detail = ActivityDetail(history: activityHistory(status: "failed", items: [
        .object(["id": .string("error"), "turnId": .string("turn"), "type": .string("error"), "text": .string("连接中断")])
    ]))
    #expect(detail.kind == .failed)
    #expect(detail.failure == "连接中断")
    #expect(detail.anchorID == "error")
}
@Test func activityKeepsOnlyActiveUnansweredQuestions() {
    let message = activityMessage("question-message", phase: "commentary", text: "问题").setting("asyncQuestions", .array([
        .object(["id": .string("live"), "active": .bool(true)]),
        .object(["id": .string("answered"), "active": .bool(true), "answer": .string("已回答")]),
        .object(["id": .string("old"), "active": .bool(false)])
    ]))
    let detail = ActivityDetail(history: activityHistory(status: "inProgress", items: [message]))
    #expect(detail.kind == .question)
    #expect(detail.questions.count == 1)
    #expect(detail.questions.first?["id"].text == "live")
    #expect(detail.anchorID == "question-message")
}
@Test func activityApprovalAnchorsToItsGroupedCommand() {
    let command: JSONValue = .object(["id": .string("turn:cmd"), "nativeId": .string("cmd"), "turnId": .string("turn"), "type": .string("commandExecution")])
    let request: JSONValue = .object(["id": .number(1), "action": .string("command-approval"), "params": .object(["itemId": .string("cmd")])])
    let detail = ActivityDetail(history: activityHistory(status: "inProgress", items: [command], requests: [request]))
    #expect(detail.kind == .approval)
    #expect(detail.requests == [request])
    #expect(detail.anchorID == "turn:cmd:process")
}
