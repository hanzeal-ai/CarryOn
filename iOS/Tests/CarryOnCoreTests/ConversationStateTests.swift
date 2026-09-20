import Testing
@testable import CarryOnCore

private func history(_ state: String, last: String = "completed", requests: [JSONValue] = []) -> JSONValue {
    .object(["thread": .object(["id": .string("child")]), "status": .object(["state": .string(state)]),
             "controls": .object(["lastTurnStatus": .string(last), "requests": .array(requests)])])
}

@Test func disconnectedAndUnloadedNeverShowCachedCompletion() {
    #expect(ConversationState.session(history("idle"), connected: false).tone == .neutral)
    #expect(ConversationState.session(history("unknown"), connected: true).label == "状态未知")
    #expect(ConversationState.session(history("notLoaded"), connected: true).label == "尚未加载")
}

@Test func runtimeAndRequestsTakePriorityOverLastTurn() {
    #expect(ConversationState.session(history("running"), connected: true).label == "执行中")
    #expect(ConversationState.session(history("running", requests: [.object(["action": .string("command-approval")])]), connected: true).label == "等待批准")
    #expect(ConversationState.session(history("waiting", requests: [.object(["action": .string("user-input")])]), connected: true).label == "等待你的回应")
    #expect(ConversationState.session(history("idle", last: "interrupted"), connected: true).label == "已中断")
    #expect(ConversationState.session(history("idle", last: "failed"), connected: true).tone == .failure)
}

@Test func pausedQueueDoesNotLookCompletedOrRunning() {
    let paused = history("idle").setting("queue", .object(["messages": .array([.object(["pausedReason": .string("interrupted")])])]))
    #expect(ConversationState.session(paused, connected: true).label == "队列已暂停")
    #expect(ConversationState.session(paused.setting("status", .object(["state": .string("running")])), connected: true).tone == .active)
}

@Test func completedCommandWithNonzeroExitIsFailureAndInterruptionIsDistinct() {
    let item: JSONValue = .object(["type": .string("commandExecution"), "status": .string("completed"), "data": .object(["exitCode": .number(1)])])
    #expect(ConversationState.activity(item).tone == .failure)
    #expect(ConversationState.activity(item.setting("status", .string("interrupted"))).label == "已中断")
    #expect(ConversationState.activity(item.setting("data", .object(["exitCode": .number(0)]))).tone == .success)
}

@Test func sideActionsRequireExactParentDeviceChildAndSnapshot() {
    let target = ConversationActionTarget(scope: "server/deviceA", threadID: "child", parentID: "parent")
    let snapshot = history("waiting").setting("parentId", .string("parent"))
    #expect(target.matches(scope: "server/deviceA", selectedThreadID: "parent", sideThreadID: "child", snapshot: snapshot))
    #expect(!target.matches(scope: "server/deviceB", selectedThreadID: "parent", sideThreadID: "child", snapshot: snapshot))
    #expect(!target.matches(scope: "server/deviceA", selectedThreadID: "other", sideThreadID: "child", snapshot: snapshot))
    #expect(!target.matches(scope: "server/deviceA", selectedThreadID: "parent", sideThreadID: "other", snapshot: snapshot))
    #expect(!target.matches(scope: "server/deviceA", selectedThreadID: "parent", sideThreadID: "child", snapshot: snapshot.setting("parentId", .string("other"))))
    #expect(target.path("operations") == "/api/side-chats/child/operations")
    #expect(target.body(["action": .string("user-input")])["parentId"] == .string("parent"))
}

@Test func explicitSideContentCapabilityDoesNotChangeResourceScope() {
    let readOnly = ConversationContentContext(parentID: "parent")
    let interactive = ConversationContentContext(parentID: "parent", isReadOnly: false)
    #expect(readOnly.isReadOnly)
    #expect(!interactive.isReadOnly)
    #expect(readOnly.resourcePath(threadID: "child", kind: "images", id: "i") == interactive.resourcePath(threadID: "child", kind: "images", id: "i"))
}

@Test func elicitationPreservesTypesAndRejectsInvalidRequiredValues() throws {
    let schema: JSONValue = .object(["type": .string("object"), "required": .array([.string("count"), .string("allowed")]), "properties": .object([
        "count": .object(["type": .string("integer"), "minimum": .number(1), "maximum": .number(3)]),
        "allowed": .object(["type": .string("boolean")]),
        "color": .object(["type": .string("string"), "enum": .array([.string("blue"), .string("red")])])])])
    let result = try ElicitationForm.response(schema, values: ["count": "2", "allowed": "false", "color": JSONValue.string("red").formatted])
    #expect(result["count"] == .number(2)); #expect(result["allowed"] == .bool(false)); #expect(result["color"] == .string("red"))
    #expect(throws: APIError.self) { try ElicitationForm.response(schema, values: ["count": "2"]) }
    #expect(throws: APIError.self) { try ElicitationForm.response(schema, values: ["count": "2.1", "allowed": "true"]) }
    #expect(throws: APIError.self) { try ElicitationForm.response(schema, values: ["count": "4", "allowed": "true"]) }
    #expect(throws: APIError.self) { try ElicitationForm.response(schema, values: ["count": "nan", "allowed": "true"]) }
}

@Test func unfamiliarSchemaDoesNotOfferAnUnvalidatedForm() {
    let nested: JSONValue = .object(["type": .string("object"), "properties": .object(["value": .object(["type": .string("object")])])])
    #expect(!ElicitationForm.supports(nested))
    #expect(!ElicitationForm.supports(nested.setting("allOf", .array([]))))
}

@Test func failedReadDoesNotPresentCachedCompletion() {
    let cached = history("idle").setting("controls", .object(["lastTurnStatus": .string("completed")]))
    #expect(ConversationState.session(cached, connected: true, readFailed: true).label == "读取失败 · 状态未知")
}

@Test func malformedElicitationSchemaFallsBackToNative() {
    let field: JSONValue = .object(["type": .string("integer")])
    let schema: JSONValue = .object(["type": .string("object"), "properties": .object(["x": field])])
    #expect(!ElicitationForm.supports(schema.setting("required", .array([.string("missing")]))))
    #expect(!ElicitationForm.supports(schema.setting("required", .string("x"))))
    #expect(!ElicitationForm.supports(schema.setting("properties", .object(["x": field.setting("enum", .array([.string("wrong")]))]))))
    #expect(!ElicitationForm.supports(schema.setting("properties", .object(["x": field.setting("minimum", .string("1"))]))))
    #expect(!ElicitationForm.supports(schema.setting("properties", .object(["x": field.setting("minimum", .number(2)).setting("enum", .array([.number(1)]))]))))
}

@Test func persistedHistoryReportsSyncSeparatelyFromRuntime() {
    let local: JSONValue = .object([
        "source": .string("local-rollout"), "syncing": .bool(false),
        "status": .object(["state": .string("notLoaded"), "label": .string("历史已同步 · 未加载")])
    ])
    #expect(ConversationState.session(local, connected: true).label == "尚未加载")
    #expect(ConversationState.session(local, connected: true).tone == .neutral)
    #expect(ConversationState.session(local, connected: true, readFailed: true).tone == .failure)
    #expect(ConversationState.session(local, connected: false).label == "状态待确认")
}
