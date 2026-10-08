import SwiftUI
import Foundation
import CarryOnCore

// Isolated entry point. Every request is intercepted; no cloud account or native socket.
@main struct CarryOnApp: App {
    @State private var fixture = AlignmentFixture()
    var body: some Scene {
        WindowGroup {
            NavigationStack { ConversationView(thread: fixture.thread) }
                .environment(fixture.model)
                .task { await fixture.run() }
        }
    }
}

private final class MockTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock()
        var jobs: [String: [String: Any]] = [:]
        var captures: [[String: Any]] = []
        var goalReply = "accepted"
        func setGoalReply(_ value: String) { lock.lock(); goalReply = value; lock.unlock() }
        var reviewState = "accepted"
        func setReviewState(_ value: String) { lock.lock(); reviewState = value; lock.unlock() }
        var creationPolls = 0
        var lostReplyIDs: Set<String> = []
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? ""
            let body = envelope["body"] as? [String: Any] ?? [:]
            captures.append(envelope)
            if path.contains("/api/jobs/") {
                let id = String(path.split(separator: "/").last ?? "")
                if lostReplyIDs.contains(id) { return ["fixtureLostReply": true] }
                if jobs[id]?["kind"] as? String == "create" {
                    creationPolls += 1
                    if creationPolls >= 2 { jobs[id]?["state"] = "completed"; jobs[id]?["createdThreadId"] = "new-native-thread" }
                }
                return jobs[id] ?? ["state": "failed", "error": "unknown fixture job"]
            }
            if path.hasSuffix("/operations") || path.hasSuffix("/compose") {
                let id = body["requestId"] as? String ?? ""
                if let action = body["action"] as? String, action.hasPrefix("goal-") {
                    let wrong = goalReply == "wrong"
                    let result: [String: Any] = action == "goal-clear" ? ["cleared": !wrong] : ["goal": ["threadId": wrong ? "other" : "fixture", "status": action == "goal-pause" ? "paused" : "active"]]
                    return ["id": id, "state": goalReply == "accepted" ? "accepted" : "completed", "threadId": "fixture", "result": result]
                }
                if body["action"] as? String == "review" { return ["id": id, "state": reviewState, "threadId": "fixture", "reviewThreadId": "fixture", "turnId": "review-turn"] }
                if body["prompt"] as? String == "live accepted lost reply" { lostReplyIDs.insert(id) }
                let failed = (body["prompt"] as? String ?? "").contains("fail")
                jobs[id] = ["id": id, "threadId": path.contains("side-chats") ? "side" : "fixture", "kind": path.hasSuffix("/compose") ? "message" : "operation:\(body["action"] ?? "")", "clientMessageId": id, "turnId": "turn-" + id, "state": (body["prompt"] as? String) == "uncertain" ? "uncertain" : failed ? "failed" : path.hasSuffix("/compose") ? "accepted" : "completed", "error": failed ? "排队消息已变化" : ""]
                return ["id": id, "state": "preparing", "threadId": path.contains("side-chats") ? "side" : "fixture", "kind": "operation:\(body["action"] ?? "")"]
            }
            if path == "/api/threads" {
                let id = body["requestId"] as? String ?? ""
                jobs[id] = ["id": id, "threadId": "", "kind": "create", "state": "accepted"]
                return jobs[id]!
            }
            if path == "/api/activity" { return ["threads": [], "total": 0, "nextOffset": 0] }
            if path.hasSuffix("/skills") { return ["cwd": "/fixture", "skills": [["name": "review-a", "path": "/fixture/a/SKILL.md", "description": "检查代码与验证证据", "enabled": true], ["name": "disabled-skill", "path": "/fixture/disabled/SKILL.md", "description": "已停用", "enabled": false]], "errors": [["path": "/fixture/broken/SKILL.md", "message": "夹具：技能元数据无效"]]] }
            if path == "/api/models" { return ["models": [["id": "fixture-model", "name": "Fixture", "efforts": ["medium"], "defaultEffort": "medium"]]] }
            return [:]
        }
        func all() -> [[String: Any]] { lock.lock(); defer { lock.unlock() }; return captures }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; bytes.append(buffer, count: n) }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let value = Self.store.respond(envelope)
        let response = HTTPURLResponse(url: request.url!, statusCode: value["fixtureLostReply"] as? Bool == true ? 503 : (envelope["body"] as? [String: Any])?["prompt"] as? String == "reject-http" ? 403 : 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: value))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor @Observable final class AlignmentFixture {
    let model = AppModel()
    let thread = try! Record(.object(["id": .string("fixture"), "title": .string("Codex 会话体验")]))
    private var ran = false
    private func snapshot(id: String, parent: String? = nil) -> JSONValue {
        let raw = """
        {"thread":{"id":"fixture"},"status":{"state":"running"},"source":"desktop-snapshot","controls":{"supportedOperations":["interrupt","steer","settings","edit","resume","compact","queue-add","queue-edit","queue-delete","queue-reorder","queue-resume","clear-queue","command-approval","user-input"],"activeTurnId":"turn","lastTurnStatus":"inProgress","requests":[{"id":7,"action":"command-approval","fingerprint":"approval-fingerprint","decisions":["accept","decline"],"params":{"command":"swift test","cwd":"/workspace/CarryOn","reason":"运行现有测试"}}]},"queue":{"fingerprint":"queue-fingerprint","messages":[{"id":"queued","text":"完成后检查图片预览","pausedReason":"interrupted","context":{"prompt":"完成后检查图片预览","imageAttachments":[]}}]},"timeline":[{"id":"user","type":"userMessage","text":"统一手机端会话体验"},{"id":"step","type":"agentMessage","text":"正在检查执行状态和队列交互。"},{"id":"command","type":"commandExecution","title":"执行命令","status":"completed","data":{"command":"swift test","cwd":"/workspace/CarryOn","aggregatedOutput":"Test suite passed.\\n61 tests, 0 failures.","exitCode":0,"durationMs":1220}},{"id":"command2","type":"commandExecution","title":"执行命令","status":"inProgress","data":{"command":"xcodebuild build","aggregatedOutput":"Compiling ConversationView.swift…"}},{"id":"agent1","type":"subAgentActivity","subagents":[{"id":"agent-a","title":"代码审查"}],"data":{"kind":"started"}},{"id":"agent2","type":"subAgentActivity","subagents":[{"id":"agent-b","title":"验证测试"}],"data":{"kind":"completed"}},{"id":"answer","type":"agentMessage","text":"执行过程会保持紧凑，详情可以展开查看。"}]}
        """
        var value = try! JSONDecoder().decode(JSONValue.self, from: Data(raw.utf8))
        value = value.setting("thread", .object(["id": .string(id)]))
        if let parent { value = value.setting("parentId", .string(parent)).setting("access", .object(["canInteract": .bool(true), "nativeReady": .bool(true)])) }
        return value
    }
    func run() async {
        guard !ran else { return }; ran = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [MockTransport.self]
        let api = ConsoleAPI(address: try! ConsoleAddress("https://ios-alignment.invalid/"), configuration: config)
        model.fixtureClient(api)
        model.addressText = "https://ios-alignment.invalid/"; model.selectedDevice = "fixture-device"
        model.devices = [try! Record(.object(["id": .string("fixture-device"), "title": .string("隔离夹具"), "online": .bool(true), "permissions": .array(["view", "send", "stop", "edit", "approve", "create"].map { .string($0) })]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true; model.foreground = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.selectedThread = thread; model.history = snapshot(id: "fixture"); model.historyRevision += 1
        // Native acceptance preserves a bubble while history is still unavailable.
        model.history = .null; model.historySynchronized = false
        let sentWithoutHistory = await model.write(path: "/api/threads/fixture/compose", target: "fixture", body: .object(["prompt": .string("accepted without history")]))
        let receiptRetainsBubble = sentWithoutHistory && model.visibleOutgoing.count == 1 && model.history == .null
        let accepted = model.visibleOutgoing.first!
        model.history = .object(["thread": .object(["id": .string("fixture")]), "timeline": .array([
            .object(["id": .string("native"), "type": .string("userMessage"), "clientMessageId": accepted["clientMessageId"], "text": .string("accepted without history")])])])
        model.reconcileOutgoing()
        let historyReplacesBubble = model.visibleOutgoing.isEmpty
        model.history = .null
        model.draft = "draft awaiting acceptance"
        let composing = Task { await model.compose() }
        try? await Task.sleep(for: .milliseconds(100))
        let pendingDraft = model.outgoing.values.first { $0["prompt"].text == "draft awaiting acceptance" }!
        model.reconcile([.object(["id": pendingDraft["id"], "state": .string("accepted")])])
        let draftRetained = model.draft == "draft awaiting acceptance" && model.writing && model.visibleOutgoing.isEmpty
        let composed = await composing.value && model.draft.isEmpty && model.visibleOutgoing.contains { $0["prompt"].text == "draft awaiting acceptance" }
        // Edit-mode text must never replace the persisted regular draft or its attachments.
        let editTestScope = "alignment-edit-isolation-" + UUID().uuidString
        let priorHistory = model.history, priorSynchronized = model.historySynchronized
        model.historySynchronized = true
        await model.draftStore.load(scope: editTestScope)
        let skillA = ComposerReference(name: "review-a", path: "/fixture/a/SKILL.md")
        let skillB = ComposerReference(name: "review-b", path: "/fixture/b/SKILL.md")
        let editItem: JSONValue = .object(["id": .string("edit-source"), "turnId": .string("edit-turn"), "type": .string("userMessage")])
        func editableHistory(_ id: String) -> JSONValue {
            .object(["thread": .object(["id": .string(id)]), "status": .object(["state": .string("idle")]),
                "controls": .object(["lastTurnId": .string("edit-turn"), "lastUserText": .string("original message"), "supportedOperations": .array([.string("edit")])])])
        }
        model.selectedThread = thread; model.history = editableHistory(thread.id)
        model.draft = "regular A"; model.draftImages = ["image-A"]; model.draftSkills = [skillA]
        model.beginEditing(editItem); model.editingDraft = "edited A"
        let editIndependent = model.editingMessage == editItem && model.editingDraft == "edited A" && model.draft == "regular A" && model.draftImages == ["image-A"] && model.draftSkills == [skillA]
        let aKey = model.scope + "\n" + thread.id
        model.selectedThread = try! Record(.object(["id": .string("fixture-B")]))
        model.history = editableHistory("fixture-B")
        model.draft = "regular B"; model.draftImages = ["image-B"]; model.draftSkills = [skillB]
        model.beginEditing(editItem); model.editingDraft = "edited B"
        let bEditingStarted = model.editingMessage == editItem && model.editingDraft == "edited B"
        model.cancelEditing()
        let editAcrossThreads = bEditingStarted && model.editingMessage == .null && model.draft == "regular B" && model.draftImages == ["image-B"] && model.draftSkills == [skillB] && model.draftStore.texts[aKey] == "regular A" && model.draftStore.images[aKey] == ["image-A"] && model.draftStore.skills[aKey] == [skillA]
        let persisted = await model.draftStore.flush()
        await model.draftStore.load(scope: editTestScope)
        model.selectedThread = thread; model.history = editableHistory(thread.id)
        let editDraftPersisted = persisted && model.draft == "regular A" && model.draftImages == ["image-A"] && model.draftSkills == [skillA]
        let writesBeforeRevocation = MockTransport.store.all().count
        let rejectedSkills = !(await model.compose())
        let revokedSkillsPreserved = rejectedSkills && MockTransport.store.all().count == writesBeforeRevocation && model.draft == "regular A" && model.draftSkills == [skillA]
        model.history = model.history.setting("controls", model.history["controls"].setting("supportsSkills", .bool(true)))
        model.draft = ""; model.draftImages = []; model.draftSkills = [skillA]
        let skillSend = Task { await model.compose() }
        try? await Task.sleep(for: .milliseconds(100))
        model.draftSkills.append(skillB)
        let skillsAccepted = await skillSend.value
        let skillBody = MockTransport.store.all().last { ($0["path"] as? String) == "/api/threads/fixture/compose" }?["body"] as? [String: Any]
        let skillsOnlySent = skillsAccepted && skillBody?["prompt"] as? String == "" && (skillBody?["skills"] as? [[String: String]]) == [["name": skillA.name, "path": skillA.path]]
        let skillsEditsPreserved = model.draftSkills == [skillA, skillB]
        model.draft = "fail skills"; model.draftSkills = [skillA]
        let skillsFailureRetained = !(await model.compose()) && model.draft == "fail skills" && model.draftSkills == [skillA]
        model.draft = ""; model.history = snapshot(id: "fixture")
        model.history = model.history.setting("controls", model.history["controls"].setting("supportsSkills", .bool(true)))
        let skillsQueued = await model.compose(queueFollowUp: true)
        let queueBody = MockTransport.store.all().last { ($0["body"] as? [String: Any])?["action"] as? String == "queue-add" }?["body"] as? [String: Any]
        let skillsQueueCleared = skillsQueued && model.draftSkills.isEmpty && (queueBody?["skills"] as? [[String: String]]) == [["name": skillA.name, "path": skillA.path]] && queueBody?["prompt"] as? String == ""
        model.draftSkills = [skillA]; model.selectedDevice = "fixture-other-scope"
        let otherEmpty = model.draftSkills.isEmpty
        model.draftSkills = [skillB]; model.selectedDevice = "fixture-device"
        let skillScopesIsolated = otherEmpty && model.draftSkills == [skillA]
        model.draft = ""; model.draftImages = []; model.draftSkills = []; model.error = nil
        model.history = priorHistory; model.historySynchronized = priorSynchronized
        model.outgoing.removeAll()
        model.draft = "live accepted lost reply"
        let lostReply = Task { await model.compose() }
        try? await Task.sleep(for: .milliseconds(100))
        let liveDraft = model.outgoing.values.first { $0["prompt"].text == "live accepted lost reply" }!
        model.reconcile([.object(["id": liveDraft["id"], "threadId": .string("fixture"), "state": .string("accepted")])])
        let liveAcceptanceWins = await lostReply.value && model.draft.isEmpty && model.visibleOutgoing.contains { $0["prompt"].text == "live accepted lost reply" }
        model.draft = "fail draft"
        let failedDraft = !(await model.compose()) && model.draft == "fail draft" && !model.visibleOutgoing.contains { $0["prompt"].text == "fail draft" }
        let failedRequestID = model.outgoing.values.first { $0["prompt"].text == "fail draft" }?["id"].text
        let retriedFailure = !(await model.compose()) && model.draft == "fail draft" && !model.writing
        let failedRetry = retriedFailure && MockTransport.store.all().contains {
            let body = $0["body"] as? [String: Any]
            return body?["prompt"] as? String == "fail draft" && body?["requestId"] as? String != failedRequestID
        }
        model.draft = "fail user cleared"
        let clearing = Task { await model.compose() }
        try? await Task.sleep(for: .milliseconds(100))
        model.draft = "" // An intentional clear must not be mistaken for untouched emptiness.
        let clearedPreserved = !(await clearing.value) && model.draft.isEmpty
        model.draft = "fail user changed images"
        let editingImages = Task { await model.compose() }
        try? await Task.sleep(for: .milliseconds(100))
        model.draftImages = ["new-image"]
        let editsPreserved = !(await editingImages.value) && model.draft == "fail user changed images" && model.draftImages == ["new-image"]
        model.outgoing.removeAll(); model.draft = ""; model.draftImages = []
        let rejected = !(await model.write(path: "/api/threads/fixture/compose", target: "fixture", body: .object(["prompt": .string("reject-http")])))
        let knownRejection = rejected && model.visibleOutgoing.last?["state"].text == "failed"
        let unknown = !(await model.write(path: "/api/threads/fixture/compose", target: "fixture", body: .object(["prompt": .string("uncertain")])))
        let unknownID = model.visibleOutgoing.first { $0["state"].text == "uncertain" }?["id"].text
        model.history = snapshot(id: "fixture"); model.historySynchronized = true
        let stopAfterUnknown = await model.operation("interrupt", fields: ["expectedTurnId": .string("turn")])
        let unknownRetained = unknown && unknownID != nil && model.visibleOutgoing.contains { $0["id"].text == unknownID }
        model.outgoing.removeAll(); model.error = nil
        let target = ConversationActionTarget(scope: model.scope, threadID: "fixture")
        let mainWithoutAccess = model.canPerform(target)
        model.history = model.history.setting("source", .string("local-preview"))
        let previewDenied = !model.canPerform(target)
        model.history = snapshot(id: "fixture").setting("access", .object(["canInteract": .bool(false)]))
        let readOnlyDenied = !model.canPerform(target)
        model.history = snapshot(id: "fixture")
        let failed = await model.operation("queue-edit", fields: ["prompt": .string("fail"), "messageId": .string("queued"), "queueFingerprint": .string("queue-fingerprint")])
        let failedReported = !failed && (model.error?.contains("已变化") ?? false)
        model.error = nil
        let success = await model.perform("queue-edit", target: target, fields: ["prompt": .string("new text"), "messageId": .string("queued"), "queueFingerprint": .string("queue-fingerprint")])
        let question: JSONValue = .object(["id": .string("q"), "title": .string("question")])
        let failedAnswer = !(await model.answer(question, text: "fail", target: target))
        model.error = nil
        let failedBubble = model.visibleOutgoing.contains { $0["state"].text == "failed" }
        let acceptedAnswer = await model.answer(question, text: "yes", target: target)
        model.sideThreadID = "side"; model.sideHistory = snapshot(id: "side", parent: "fixture")
        let side = ConversationActionTarget(scope: model.scope, threadID: "side", parentID: "fixture")
        let sideSuccess = await model.perform("user-input", target: side, fields: ["nativeRequestId": .number(7), "requestFingerprint": .string("side-fingerprint"), "answers": .object(["q": .array([.string("yes")])])])
        model.sideThreadID = "another-side"
        let staleDenied = !model.canPerform(side)
        model.sideThreadID = nil; model.error = nil; model.historyRevision += 1
        let created = await model.write(path: "/api/threads", target: "new", body: .object(["prompt": .string("create fixture")]))
        let creationWaited = created && MockTransport.store.creationPolls == 2
        model.outgoing.removeAll()
        try? await Task.sleep(for: .seconds(2))
        model.history = editableHistory("fixture").setting("source", .string("desktop-snapshot"))
        model.historySynchronized = true
        let reviewTarget: JSONValue = .object(["type": .string("custom"), "instructions": .string("Inspect scope safety")])
        MockTransport.store.setReviewState("accepted")
        let reviewAcceptedUnconfirmed = !(await model.operation("review", fields: ["target": reviewTarget]))
        MockTransport.store.setReviewState("inProgress")
        let reviewInProgressUnconfirmed = !(await model.operation("review", fields: ["target": reviewTarget]))
        MockTransport.store.setReviewState("completed")
        let reviewCompleted = await model.operation("review", fields: ["target": reviewTarget])
        let reviewWrites = MockTransport.store.all().filter { ($0["body"] as? [String: Any])?["action"] as? String == "review" }
        let reviewIDs = reviewWrites.compactMap { ($0["body"] as? [String: Any])?["requestId"] as? String }
        let reviewIdentityRetained = reviewAcceptedUnconfirmed && reviewInProgressUnconfirmed && reviewCompleted && reviewIDs.count == 3 && Set(reviewIDs).count == 1
        model.history = snapshot(id: "fixture").setting("controls", .object(["canSteer": .bool(false), "supportedOperations": .array([.string("interrupt")])]))
        model.draft = "preserve while review runs"
        let beforeNoSteer = MockTransport.store.all().count
        let noSteerPreservesDraft = !(await model.compose()) && MockTransport.store.all().count == beforeNoSteer && model.draft == "preserve while review runs"
        model.draft = ""; model.error = nil; model.history = snapshot(id: "fixture")
        model.history = editableHistory("fixture").setting("source", .string("desktop-snapshot"))
        let goalFields: [String: JSONValue] = ["objective": .string("Check target isolation"), "status": .string("active")]
        var goalReceiptsConfirmed = true
        for action in ["goal-set", "goal-pause", "goal-clear"] {
            let fields = action == "goal-set" ? goalFields : [:]
            MockTransport.store.setGoalReply("accepted")
            let acceptedUnconfirmed = !(await model.operation(action, fields: fields))
            MockTransport.store.setGoalReply("wrong")
            let wrongUnconfirmed = !(await model.operation(action, fields: fields))
            MockTransport.store.setGoalReply("completed")
            let confirmed = await model.operation(action, fields: fields)
            let bodies = MockTransport.store.all().compactMap { $0["body"] as? [String: Any] }.filter { $0["action"] as? String == action }
            let ids = bodies.compactMap { $0["requestId"] as? String }
            goalReceiptsConfirmed = goalReceiptsConfirmed && acceptedUnconfirmed && wrongUnconfirmed && confirmed && ids.count == 3 && Set(ids).count == 1
        }
        let originalDevices = model.devices
        model.devices = [try! Record(.object(["id": .string("fixture-device"), "permissions": .array([.string("view"), .string("send")])]))]
        let goalTarget = ConversationActionTarget(scope: model.scope, threadID: "fixture")
        let sendOnlyGoals = model.canPerform(goalTarget, action: "goal-set") && !model.canPerform(goalTarget, action: "goal-pause") && !model.canPerform(goalTarget, action: "goal-clear")
        let beforeDeniedGoals = MockTransport.store.all().count
        let pauseDenied = !(await model.operation("goal-pause"))
        model.devices = [try! Record(.object(["id": .string("fixture-device"), "permissions": .array([.string("view"), .string("stop")])]))]
        let stopOnlyGoals = !model.canPerform(goalTarget, action: "goal-set") && model.canPerform(goalTarget, action: "goal-pause") && model.canPerform(goalTarget, action: "goal-clear")
        let setDenied = !(await model.operation("goal-set", fields: goalFields))
        model.devices = originalDevices
        let staleGoal = ConversationActionTarget(scope: "old-scope", threadID: "fixture")
        let staleGoalDenied = !(await model.perform("goal-set", target: staleGoal, fields: goalFields))
        let goalPermissionIsolation = sendOnlyGoals && stopOnlyGoals && pauseDenied && setDenied && staleGoalDenied && MockTransport.store.all().count == beforeDeniedGoals
        model.error = nil; model.history = snapshot(id: "fixture")
        let captures = MockTransport.store.all()
        let polls = captures.filter { ($0["path"] as? String ?? "").contains("/api/jobs/") }.count
        let sideBody = captures.first { ($0["path"] as? String) == "/api/side-chats/side/operations" }?["body"] as? [String: Any]
        let result: [String: Any] = ["goalReceiptsPreserveIdentity": goalReceiptsConfirmed, "goalPermissionScopeIsolation": goalPermissionIsolation, "reviewConfirmationPreservesIdentity": reviewIdentityRetained, "noSteerPreservesDraft": noSteerPreservesDraft, "skillsOnlyComposePayload": skillsOnlySent, "skillsEditedDuringSendRetained": skillsEditsPreserved, "skillsFailureRetainsDraft": skillsFailureRetained, "skillsOnlyQueueClearsSnapshot": skillsQueueCleared, "skillWorkspaceScopesIsolated": skillScopesIsolated, "editingKeepsRegularDraft": editIndependent, "editingAcrossThreadsPreservesDrafts": editAcrossThreads, "regularDraftPersistsDuringEditing": editDraftPersisted, "revokedSkillsPreserveDraft": revokedSkillsPreserved, "failedJobNotAccepted": failedReported, "completedJobAccepted": success, "sideOperationAccepted": sideSuccess, "staleSideDenied": staleDenied, "parentPreserved": sideBody?["parentId"] as? String == "fixture", "jobPolls": polls, "mainWithoutAccess": mainWithoutAccess, "previewDenied": previewDenied, "readOnlyDenied": readOnlyDenied, "failedAnswerRetained": failedAnswer, "acceptedAnswerConfirmed": acceptedAnswer, "receiptRetainsBubbleWithoutHistory": receiptRetainsBubble, "historyReplacesBubble": historyReplacesBubble, "draftRetainedWhileSending": draftRetained, "successfulSendClearsDraft": composed, "failedDraftRetained": failedDraft, "failedDraftCanRetry": failedRetry, "liveAcceptanceSurvivesLostHTTPReply": liveAcceptanceWins, "userClearedDraftPreserved": clearedPreserved, "userImageEditPreserved": editsPreserved, "explicitHTTPRejectionIsFailed": knownRejection, "stopAfterUnknown": stopAfterUnknown, "unknownIDRetained": unknownRetained, "failedBubbleUpdated": failedBubble, "creationWaitedForNativeId": creationWaited, "passed": goalReceiptsConfirmed && goalPermissionIsolation && reviewIdentityRetained && noSteerPreservesDraft && skillsOnlySent && skillsEditsPreserved && skillsFailureRetained && skillsQueueCleared && skillScopesIsolated && editIndependent && editAcrossThreads && editDraftPersisted && revokedSkillsPreserved && creationWaited && failedBubble && receiptRetainsBubble && historyReplacesBubble && draftRetained && composed && liveAcceptanceWins && failedDraft && failedRetry && clearedPreserved && editsPreserved && knownRejection && stopAfterUnknown && unknownRetained && failedAnswer && acceptedAnswer && mainWithoutAccess && previewDenied && readOnlyDenied && failedReported && success && sideSuccess && staleDenied && polls >= 3 && sideBody?["parentId"] as? String == "fixture"]
        let output = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        do {
            try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
            if let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first?.windows.first {
                let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
                try image.pngData()?.write(to: output.appendingPathComponent("alignment.png"))
            }
            try JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: output.appendingPathComponent("alignment-result.json"))
        } catch { fatalError("Fixture result write failed: \(error)") }
        print("ALIGNMENT_RESULT \(output.path)")
    }
}
