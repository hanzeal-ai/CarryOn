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
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? ""
            let body = envelope["body"] as? [String: Any] ?? [:]
            captures.append(envelope)
            if path.contains("/api/jobs/") {
                let id = String(path.split(separator: "/").last ?? "")
                return jobs[id] ?? ["state": "failed", "error": "unknown fixture job"]
            }
            if path.hasSuffix("/operations") || path.hasSuffix("/compose") {
                let id = body["requestId"] as? String ?? ""
                let failed = (body["prompt"] as? String ?? "").contains("fail")
                jobs[id] = ["id": id, "threadId": path.contains("side-chats") ? "side" : "fixture", "kind": "operation:\(body["action"] ?? "")", "state": failed ? "failed" : path.hasSuffix("/compose") ? "accepted" : "completed", "error": failed ? "排队消息已变化" : ""]
                return ["id": id, "state": "preparing", "threadId": path.contains("side-chats") ? "side" : "fixture", "kind": "operation:\(body["action"] ?? "")"]
            }
            if path == "/api/activity" { return ["threads": [], "total": 0, "nextOffset": 0] }
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
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
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
        {"thread":{"id":"fixture"},"status":{"state":"running"},"source":"desktop-snapshot","controls":{"activeTurnId":"turn","lastTurnStatus":"inProgress","requests":[{"id":7,"action":"command-approval","fingerprint":"approval-fingerprint","decisions":["accept","decline"],"params":{"command":"swift test","cwd":"/workspace/CarryOn","reason":"运行现有测试"}}]},"queue":{"fingerprint":"queue-fingerprint","messages":[{"id":"queued","text":"完成后检查图片预览","pausedReason":"interrupted","context":{"prompt":"完成后检查图片预览","imageAttachments":[]}}]},"timeline":[{"id":"user","type":"userMessage","text":"统一手机端会话体验"},{"id":"step","type":"agentMessage","text":"正在检查执行状态和队列交互。"},{"id":"command","type":"commandExecution","title":"执行命令","status":"completed","data":{"command":"swift test","cwd":"/workspace/CarryOn","aggregatedOutput":"Test suite passed.\\n61 tests, 0 failures.","exitCode":0,"durationMs":1220}},{"id":"command2","type":"commandExecution","title":"执行命令","status":"inProgress","data":{"command":"xcodebuild build","aggregatedOutput":"Compiling ConversationView.swift…"}},{"id":"agent1","type":"subAgentActivity","subagents":[{"id":"agent-a","title":"代码审查"}],"data":{"kind":"started"}},{"id":"agent2","type":"subAgentActivity","subagents":[{"id":"agent-b","title":"验证测试"}],"data":{"kind":"completed"}},{"id":"answer","type":"agentMessage","text":"执行过程会保持紧凑，详情可以展开查看。"}]}
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
        model.devices = [try! Record(.object(["id": .string("fixture-device"), "title": .string("隔离夹具"), "online": .bool(true)]))]
        model.authenticated = true; model.connected = true; model.foreground = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true)])
        model.selectedThread = thread; model.history = snapshot(id: "fixture"); model.historyRevision += 1
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
        let acceptedAnswer = await model.answer(question, text: "yes", target: target)
        model.sideThreadID = "side"; model.sideHistory = snapshot(id: "side", parent: "fixture")
        let side = ConversationActionTarget(scope: model.scope, threadID: "side", parentID: "fixture")
        let sideSuccess = await model.perform("user-input", target: side, fields: ["nativeRequestId": .number(7), "requestFingerprint": .string("side-fingerprint"), "answers": .object(["q": .array([.string("yes")])])])
        model.sideThreadID = "another-side"
        let staleDenied = !model.canPerform(side)
        model.sideThreadID = nil; model.error = nil; model.historyRevision += 1
        let captures = MockTransport.store.all()
        let polls = captures.filter { ($0["path"] as? String ?? "").contains("/api/jobs/") }.count
        let sideBody = captures.first { ($0["path"] as? String) == "/api/side-chats/side/operations" }?["body"] as? [String: Any]
        let result: [String: Any] = ["failedJobNotAccepted": failedReported, "completedJobAccepted": success, "sideOperationAccepted": sideSuccess, "staleSideDenied": staleDenied, "parentPreserved": sideBody?["parentId"] as? String == "fixture", "jobPolls": polls, "mainWithoutAccess": mainWithoutAccess, "previewDenied": previewDenied, "readOnlyDenied": readOnlyDenied, "failedAnswerRetained": failedAnswer, "acceptedAnswerConfirmed": acceptedAnswer, "passed": failedAnswer && acceptedAnswer && mainWithoutAccess && previewDenied && readOnlyDenied && failedReported && success && sideSuccess && staleDenied && polls >= 3 && sideBody?["parentId"] as? String == "fixture"]
        let output = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        do {
            try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
            try JSONSerialization.data(withJSONObject: result, options: .prettyPrinted).write(to: output.appendingPathComponent("alignment-result.json"))
        } catch { fatalError("Fixture result write failed: \(error)") }
        print("ALIGNMENT_RESULT \(output.path)")
    }
}
