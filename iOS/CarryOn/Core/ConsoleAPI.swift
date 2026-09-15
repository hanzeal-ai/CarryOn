import Foundation

public struct ConsoleAddress: Sendable, Equatable {
    public let base: URL
    public let origin: String
    public init(_ raw: String) throws {
        guard var parts = URLComponents(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              parts.scheme?.lowercased() == "https", let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              !parts.path.split(separator: "/").contains(where: { $0 == ".." || $0 == "." }) else {
            throw APIError("请输入完整的 HTTPS 云端地址，不包含凭证、查询参数或片段")
        }
        parts.scheme = "https"
        parts.path = parts.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        parts.path = parts.path.isEmpty ? "/" : "/" + parts.path + "/"
        guard let url = parts.url else { throw APIError("云端地址无效") }
        base = url
        parts.path = ""; origin = parts.string ?? ""
    }
    public func url(_ route: String) throws -> URL {
        guard !route.hasPrefix("/"), !route.contains(".."), !route.contains("#"),
              let result = URL(string: "console/" + route, relativeTo: base)?.absoluteURL,
              result.host == base.host, result.scheme == base.scheme, result.port == base.port else {
            throw APIError("接口路径无效")
        }
        return result
    }
    public func socketURL(deviceID: String) throws -> URL {
        let http = try url("devices/\(Self.component(deviceID))/ws")
        guard var parts = URLComponents(url: http, resolvingAgainstBaseURL: false) else { throw APIError("实时连接地址无效") }
        parts.scheme = "wss"
        guard let result = parts.url else { throw APIError("实时连接地址无效") }
        return result
    }
    public static func component(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))) ?? ""
    }
}

/// Redirects are rejected so a configured endpoint cannot forward login secrets elsewhere.
private final class RedirectGuard: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

public actor ConsoleAPI {
    public let address: ConsoleAddress
    private let session: URLSession
    private var cookie: String?
    private var loginCookie: String?
    private let credentials: (any SessionCredentials)?
    public init(address: ConsoleAddress, configuration: URLSessionConfiguration = .ephemeral, credentials: (any SessionCredentials)? = nil) {
        self.address = address
        self.credentials = credentials
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 35
        configuration.timeoutIntervalForResource = 45
        session = URLSession(configuration: configuration, delegate: RedirectGuard(), delegateQueue: nil)
    }
    public func request(_ route: String, body: JSONValue? = nil, method: String? = nil) async throws -> JSONValue {
        var request = URLRequest(url: try address.url(route))
        request.httpMethod = method ?? (body == nil ? "GET" : "POST")
        request.setValue(address.origin, forHTTPHeaderField: "Origin")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let requestCookie = cookie
        if let requestCookie { request.setValue("carryon-console=" + requestCookie, forHTTPHeaderField: "Cookie") }
        if let body { request.httpBody = try body.encoded(); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw APIError("服务器响应无效") }
        if response.statusCode == 401 {
            if cookie == requestCookie { cookie = nil }
            do {
                if let requestCookie { try credentials?.remove(server: address.base.absoluteString, matching: requestCookie) }
            }
            catch { throw APIError("登录已失效，安全保存的状态未能清除，请重新登录", status: 401) }
        }
        let result = try? JSONDecoder().decode(JSONValue.self, from: data)
        guard (200..<300).contains(response.statusCode) else {
            throw APIError(result?["error"].string ?? "请求失败（HTTP \(response.statusCode)）", status: response.statusCode)
        }
        guard let result, result.object != nil else { throw APIError("服务器返回了无效数据") }
        if route == "login" || route == "register" || (route == "qr/poll" && result["authenticated"].bool == true) {
            let fields = response.allHeaderFields.reduce(into: [String: String]()) { $0[String(describing: $1.key)] = String(describing: $1.value) }
            guard let token = HTTPCookie.cookies(withResponseHeaderFields: fields, for: request.url!).first(where: { $0.name == "carryon-console" })?.value,
                  !token.isEmpty else { throw APIError("登录响应缺少会话凭证") }
            cookie = token
            loginCookie = token
        }
        if route == "logout" {
            if cookie == requestCookie { cookie = nil }
            if let requestCookie { try credentials?.remove(server: address.base.absoluteString, matching: requestCookie) }
        }
        return result
    }
    /// A new session stays in memory until its directory is valid and initialization is not cancelled.
    public func completeLogin() async throws -> [Record] {
        let result = try await request("session")
        guard case .array(let values) = result["devices"] else { throw APIError("设备目录格式不正确") }
        let devices = try values.map(Record.init)
        try Task.checkCancellation()
        guard let token = loginCookie, token == cookie else { throw APIError("登录会话无效") }
        try credentials?.save(token, server: address.base.absoluteString)
        return devices
    }

    /// Cleanup runs independently of the cancelled UI task; it only targets this new session.
    public func cancelLogin() async throws {
        guard let token = loginCookie else { invalidate(); return }
        loginCookie = nil
        var cleanupErrors: [String] = []
        do {
            try credentials?.remove(server: address.base.absoluteString, matching: token)
        } catch { cleanupErrors.append("新登录凭证未能从本机清除") }
        do {
            var request = URLRequest(url: try address.url("logout"))
            request.httpMethod = "POST"
            request.setValue(address.origin, forHTTPHeaderField: "Origin")
            request.setValue("carryon-console=" + token, forHTTPHeaderField: "Cookie")
            let session = session
            let cleanupRequest = request
            let status = try await Task.detached {
                let (_, response) = try await session.data(for: cleanupRequest)
                return (response as? HTTPURLResponse)?.statusCode
            }.value
            guard let status, (200..<300).contains(status) || status == 401 else {
                throw APIError("会话撤销未确认")
            }
        } catch { cleanupErrors.append("未能确认服务端撤销新登录，请恢复网络后在服务端核对会话") }
        invalidate()
        if !cleanupErrors.isEmpty { throw APIError(cleanupErrors.joined(separator: "；")) }
    }
    public func device(_ id: String, path: String, body: JSONValue? = nil) async throws -> JSONValue {
        guard path.hasPrefix("/api/"), !path.contains("#") else { throw APIError("设备接口路径无效") }
        return try await request("devices/\(ConsoleAddress.component(id))/request", body: .object([
            "method": .string(body == nil ? "GET" : "POST"), "path": .string(path), "body": body ?? .null
        ]))
    }
    public func stream(deviceID: String, selection: JSONValue) async throws -> ConsoleStream {
        guard let cookie else { throw APIError("请先登录云端控制台", status: 401) }
        var request = URLRequest(url: try address.socketURL(deviceID: deviceID))
        request.setValue(address.origin, forHTTPHeaderField: "Origin")
        request.setValue("carryon-console=" + cookie, forHTTPHeaderField: "Cookie")
        let task = session.webSocketTask(with: request)
        task.maximumMessageSize = 32 * 1024 * 1024
        let stream = ConsoleStream(task: task, subscription: selection["subscription"].text)
        task.resume()
        do {
            let payload = try selection.setting("type", .string("subscribe")).encoded()
            guard let text = String(data: payload, encoding: .utf8) else { throw APIError("订阅参数无效") }
            try await withTaskCancellationHandler {
                try await task.send(.string(text))
                try Task.checkCancellation()
            } onCancel: { stream.close() }
            return stream
        } catch { stream.close(); throw error }
    }
    public func restoreSession() throws -> Bool {
        cookie = try credentials?.load(server: address.base.absoluteString)
        return cookie != nil
    }
    public func invalidate() { cookie = nil; session.invalidateAndCancel() }
}


/// One ordered read stream. Cancellation never retries a submitted operation.
protocol ConsoleSocket: Sendable {
    func send(_ message: URLSessionWebSocketTask.Message) async throws
    func receive() async throws -> URLSessionWebSocketTask.Message
    func sendPing(pongReceiveHandler: @escaping @Sendable (Error?) -> Void)
    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?)
}
extension URLSessionWebSocketTask: ConsoleSocket {}

public final class ConsoleStream: @unchecked Sendable {
    private let task: any ConsoleSocket
    private let selectionLock = NSLock()
    private var subscription: String
    private var supportsResubscribe = false
    private var historyWire = HistoryWireProjection()
    private var receiveDeadline: ContinuousClock.Instant? = .now.advanced(by: .seconds(45))
    public func setForeground(_ active: Bool) {
        selectionLock.withLock { receiveDeadline = active ? .now.advanced(by: .seconds(45)) : nil }
    }
    public func checkHealth() async throws {
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask {
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    self.task.sendPing { error in
                        if let error { continuation.resume(throwing: error) }
                        else { continuation.resume() }
                    }
                }
            }
            group.addTask {
                try await Task.sleep(for: .seconds(8))
                self.close()
                throw APIError("实时连接检查超时")
            }
            defer { group.cancelAll() }
            _ = try await group.next()
        }
    }
    public var canResubscribe: Bool { selectionLock.withLock { supportsResubscribe } }
    init(task: any ConsoleSocket, subscription: String) {
        self.task = task; self.subscription = subscription
    }
    public func resubscribe(_ selection: JSONValue) async throws {
        let payload = try selection.setting("type", .string("subscribe")).encoded()
        let text = String(decoding: payload, as: UTF8.self)
        guard canResubscribe else { throw APIError("此服务端需要重新建立订阅") }
        selectionLock.withLock { subscription = selection["subscription"].text }
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask { try await self.task.send(.string(text)) }
            group.addTask {
                try await Task.sleep(for: .seconds(8))
                self.close()
                throw APIError("实时订阅更新超时")
            }
            defer { group.cancelAll() }
            _ = try await group.next()
        }
    }
    public func next() async throws -> JSONValue {
        try await withTaskCancellationHandler {
            while true {
                try Task.checkCancellation()
                let message = try await receiveWithTimeout()
                let data: Data
                switch message {
                case .data(let value): data = value
                case .string(let value): data = Data(value.utf8)
                @unknown default: throw APIError("实时更新格式无效")
                }
                let packet = try JSONDecoder().decode(JSONValue.self, from: data)
                if packet["type"].text == "ping" { try await task.send(.string("{\"type\":\"pong\"}")); continue }
                if packet["type"].text == "error" { throw APIError(packet["error"].string ?? "实时订阅失败", status: packet["status"].int ?? 500) }
                guard packet["type"].text == "update", packet["body"]["type"].text == "update" else { throw APIError("实时更新格式无效") }
                let body: JSONValue? = try selectionLock.withLock {
                    guard packet["subscription"].text == subscription else { return nil }
                    supportsResubscribe = packet["resubscribe"].bool == true
                    return try historyWire.decode(packet["body"])
                }
                if let body { return body }
            }
        } onCancel: { self.close() }
    }
    private func receiveWithTimeout() async throws -> URLSessionWebSocketTask.Message {
        selectionLock.withLock {
            if receiveDeadline != nil { receiveDeadline = .now.advanced(by: .seconds(45)) }
        }
        return try await withThrowingTaskGroup(of: URLSessionWebSocketTask.Message.self) { group in
            group.addTask { try await self.task.receive() }
            group.addTask {
                while true {
                    try await Task.sleep(for: .seconds(1))
                    let expired = self.selectionLock.withLock {
                        self.receiveDeadline.map { ContinuousClock.now >= $0 } ?? false
                    }
                    if expired {
                        self.close()
                        throw APIError("实时连接超时，请重新连接")
                    }
                }
            }
            defer { group.cancelAll() }
            guard let message = try await group.next() else { throw CancellationError() }
            return message
        }
    }
    public func close() { task.cancel(with: .goingAway, reason: nil) }
}
