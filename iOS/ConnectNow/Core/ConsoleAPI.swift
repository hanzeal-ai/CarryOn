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
    public init(address: ConsoleAddress, configuration: URLSessionConfiguration = .ephemeral) {
        self.address = address
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
        if let cookie { request.setValue("connectnow-console=" + cookie, forHTTPHeaderField: "Cookie") }
        if let body { request.httpBody = try body.encoded(); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw APIError("服务器响应无效") }
        if response.statusCode == 401 { cookie = nil }
        let result = try? JSONDecoder().decode(JSONValue.self, from: data)
        guard (200..<300).contains(response.statusCode) else {
            throw APIError(result?["error"].string ?? "请求失败（HTTP \(response.statusCode)）", status: response.statusCode)
        }
        guard let result, result.object != nil else { throw APIError("服务器返回了无效数据") }
        if route == "login" {
            let fields = response.allHeaderFields.reduce(into: [String: String]()) { $0[String(describing: $1.key)] = String(describing: $1.value) }
            guard let token = HTTPCookie.cookies(withResponseHeaderFields: fields, for: request.url!).first(where: { $0.name == "connectnow-console" })?.value,
                  !token.isEmpty else { throw APIError("登录响应缺少会话凭证") }
            cookie = token
        }
        if route == "logout" { cookie = nil }
        return result
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
        request.setValue("connectnow-console=" + cookie, forHTTPHeaderField: "Cookie")
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
    public func invalidate() { cookie = nil; session.invalidateAndCancel() }
}


/// One ordered read stream. Cancellation never retries a submitted operation.
public final class ConsoleStream: Sendable {
    private let task: URLSessionWebSocketTask
    private let subscription: String
    fileprivate init(task: URLSessionWebSocketTask, subscription: String) {
        self.task = task; self.subscription = subscription
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
                guard packet["type"].text == "update", packet["subscription"].text == subscription,
                      packet["body"]["type"].text == "update" else { throw APIError("实时更新与当前订阅不匹配") }
                return packet["body"]
            }
        } onCancel: { self.close() }
    }
    private func receiveWithTimeout() async throws -> URLSessionWebSocketTask.Message {
        try await withThrowingTaskGroup(of: URLSessionWebSocketTask.Message.self) { group in
            group.addTask { try await self.task.receive() }
            group.addTask {
                try await Task.sleep(for: .seconds(45))
                self.close()
                throw APIError("实时连接超时，请重新连接")
            }
            defer { group.cancelAll() }
            guard let message = try await group.next() else { throw CancellationError() }
            return message
        }
    }
    public func close() { task.cancel(with: .goingAway, reason: nil) }
}
