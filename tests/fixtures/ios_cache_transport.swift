import Foundation

public final class CacheProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var counts: [String: Int] = [:]
    nonisolated(unsafe) private static var running = (0..<4).map { "running-\($0)" }
    public static var runningIDs: [String] {
        get { lock.withLock { running } }
        set { lock.withLock { running = newValue } }
    }
    public static func count(_ path: String) -> Int { lock.withLock { counts[path, default: 0] } }
    public static var configuration: URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [Self.self]; return config
    }
    public override class func canInit(with request: URLRequest) -> Bool { true }
    public override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    public override func startLoading() {
        var data = request.httpBody
        if data == nil, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = Data(), buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }; bytes.append(contentsOf: buffer.prefix(count))
            }
            data = bytes
        }
        let body = data.flatMap { try? JSONDecoder().decode(JSONValue.self, from: $0) } ?? .null
        let path = body["path"].string ?? request.url!.path
        Self.lock.withLock { Self.counts[path, default: 0] += 1 }
        let devices: [JSONValue] = ["fixture", "other"].map { .object(["id": .string($0), "title": .string($0), "online": .bool(true), "permissions": .array([.string("view")])]) }
        var result: JSONValue = .object(["account": .object(["id": .string("fixture-account")]), "devices": .array(devices), "requests": .array([]), "history": .array([])])
        if path.hasSuffix("/binding/pending") {
            result = .object(["requests": .array([.object(["id": .string("binding-fixture"), "name": .string("工作区绑定申请"), "account": .object(["username": .string("fixture")]), "permissions": .array([.string("view")])])])])
        }
        else if path.hasPrefix("/api/workspace/threads?threadId=") {
            Thread.sleep(forTimeInterval: 0.3)
            let id = String(path.split(separator: "=").last!)
            result = .object(["threads": .array([.object(["id": .string(id), "title": .string(id)])]), "total": .number(1), "nextOffset": .number(1)])
        }
        else if path.contains("/history?") {
            let id = String(path.split(separator: "/")[2])
            result = .object(["thread": .object(["id": .string(id)]), "timeline": .array([
                .object(["id": .string("activity-turn"), "type": .string("turn"), "turnId": .string("last-turn"), "status": .string("completed")]),
                .object(["id": .string("activity-result"), "type": .string("agentMessage"), "turnId": .string("last-turn"), "phase": .string("final"), "text": .string("最后一次返回的结果：**验证完成**。")])
            ])])
        }
        else if path == "/api/notifications/read" { result = .object(["readThrough": .number(1)]) }
        else if path == "/api/standby" { result = .object(["supported": .bool(true), "enabled": .bool(true), "effective": .bool(true)]) }
        else if path == "/api/status" { result = .object(["deviceInfo": .object(["hostname": .string("Fixture Mac"), "listenHost": .string("127.0.0.1"), "port": .number(9000)])]) }
        else if path == "/api/usage" {
            let window: JSONValue = .object(["id": .string("primary"), "usedPercent": .number(20), "windowDurationMins": .number(300)])
            let limit: JSONValue = .object(["id": .string("codex"), "name": .string("Codex"), "windows": .array([window])])
            result = .object(["limits": .array([limit])])
        }
        else if path.contains("filter=running") {
            result = .object(["threads": .array(Self.runningIDs.map { .object(["id": .string($0), "title": .string("执行中任务 " + $0)]) }), "total": .number(4), "nextOffset": .number(4)])
        } else if path.hasPrefix("/api/activity") {
            let availableOnly = path.contains("availableOnly=true")
            let ids = availableOnly ? ["activity-completed"] : ["activity-completed", "activity-inactive"]
            let rows: [JSONValue] = ids.filter { !path.contains("excludeThreadId=" + $0) }.map {
                .object(["id": .string($0), "title": .string($0 == "activity-completed" ? "任务完成结果" : "未活跃任务"), "activityKind": .string("completed"), "unread": .bool(true), "readSequence": .number(1)])
            }
            result = .object(["threads": .array(rows), "total": .number(Double(rows.count)), "nextOffset": .number(Double(rows.count))])
        }
        else if path.hasPrefix("/api/projects?") { result = .object(["projects": .array([.object(["id": .string("project"), "name": .string("缓存项目")])]), "total": .number(1), "nextOffset": .number(1)]) }
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! result.encoded()); client?.urlProtocolDidFinishLoading(self)
    }
    public override func stopLoading() {}
}

public final class CacheSocket: ConsoleSocket, @unchecked Sendable {
    private static let registryLock = NSLock()
    nonisolated(unsafe) private static var active: Set<UUID> = []
    nonisolated(unsafe) private static var watched: [UUID: String] = [:]
    public static var watchedThreads: [String] { registryLock.withLock { Array(watched.values) } }
    public static var activeCount: Int { registryLock.withLock { active.count } }
    public static func connectionIDs(for thread: String) -> Set<UUID> {
        registryLock.withLock { Set(watched.filter { $0.value == thread }.keys) }
    }
    nonisolated(unsafe) private static var subscriptions: [String: Int] = [:]
    public static func subscriptionCount(for thread: String) -> Int {
        registryLock.withLock { subscriptions[thread, default: 0] }
    }
    private let id = UUID(), lock = NSLock()
    private var selection: JSONValue = .null
    private var closed = false
    private var revision = 0
    init() { _ = Self.registryLock.withLock { Self.active.insert(id) } }
    public static func connect(_ selection: JSONValue) async throws -> ConsoleStream {
        let socket = CacheSocket()
        let stream = ConsoleStream(task: socket, subscription: selection["subscription"].text)
        try await stream.subscribe(selection); return stream
    }
    func send(_ message: URLSessionWebSocketTask.Message) async throws {
        if case .string(let text) = message, let value = try? JSONDecoder().decode(JSONValue.self, from: Data(text.utf8)), value["type"].text == "subscribe" {
            lock.withLock { selection = value }
            Self.registryLock.withLock {
                Self.watched[id] = value["threadId"].string
                if let thread = value["threadId"].string { Self.subscriptions[thread, default: 0] += 1 }
            }
        }
    }
    func receive() async throws -> URLSessionWebSocketTask.Message {
        try await Task.sleep(for: .milliseconds(200))
        let selected = try lock.withLock {
            if closed { throw URLError(.cancelled) }
            revision += 1; return selection
        }
        var body: JSONValue = .object(["type": .string("update"), "threadId": selected["threadId"], "status": .object(["enabled": .bool(true), "remoteControl": .bool(false)]), "jobs": .array([])])
        if let thread = selected["threadId"].string {
            body = body.setting("history", .object(["thread": .object(["id": .string(thread)]), "status": .object(["state": .string(CacheProtocol.runningIDs.contains(thread) ? "running" : "idle")]), "historyRevision": .string("\(revision)"), "timeline": .array([.object(["id": .string("message"), "type": .string("agentMessage"), "text": .string("后台已同步的任务消息 · \(revision)")])])]))
        }
        return .data(try JSONValue.object(["type": .string("update"), "subscription": selected["subscription"], "resubscribe": .bool(true), "body": body]).encoded())
    }
    func sendPing(pongReceiveHandler: @escaping @Sendable (Error?) -> Void) { pongReceiveHandler(nil) }
    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        lock.withLock { closed = true }; Self.registryLock.withLock { Self.active.remove(id); Self.watched[id] = nil }
    }
}
