import Foundation

// Compiled only into the isolated startup regression app, never the shipped package.
public final class StartupProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var responseMode = "stall"
    nonisolated(unsafe) private static var readThrough = 0
    public static var mode: String {
        get { lock.withLock { responseMode } }
        set { lock.withLock { responseMode = newValue } }
    }
    public static var configuration: URLSessionConfiguration {
        let result = URLSessionConfiguration.ephemeral
        result.protocolClasses = [StartupProtocol.self]
        return result
    }
    public override class func canInit(with request: URLRequest) -> Bool { true }
    public override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    public override func startLoading() {
        guard Self.mode != "stall" else { return }
        let status = Self.mode == "expired" ? 401 : 200
        let login = request.url!.path.hasSuffix("/login")
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
            headerFields: login ? ["Set-Cookie": "carryon-console=fixture-session; Path=/console/; Secure; HttpOnly"] : nil)!
        var body = #"{"account":{"id":"fixture-account"},"devices":[],"requests":[],"history":[]}"#
        if Self.mode == "interactive" {
            body = #"{"devices":[{"id":"fixture","title":"测试工作区","online":false,"permissions":["view"]}],"requests":[],"history":[]}"#
            var requestData = request.httpBody
            if requestData == nil, let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }
                var data = Data(), buffer = [UInt8](repeating: 0, count: 4096)
                while stream.hasBytesAvailable {
                    let count = stream.read(&buffer, maxLength: buffer.count)
                    if count <= 0 { break }
                    data.append(contentsOf: buffer.prefix(count))
                }
                requestData = data
            }
            if let data = requestData, let fields = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let path = fields["path"] as? String {
                if path.hasPrefix("/api/activity?") {
                    let unread = Self.lock.withLock { Self.readThrough == 0 }
                    let rows: [[String: Any]] = [
                        ["id": "thread", "title": "未读任务结果", "projectName": "测试工作区", "unread": unread, "activityRead": !unread, "readSequence": 1, "activityKind": "completed"],
                        ["id": "read-thread", "title": "已读任务结果", "projectName": "测试工作区", "unread": false, "activityRead": true, "readSequence": 1, "activityKind": "completed"]
                    ]
                    body = String(decoding: try! JSONSerialization.data(withJSONObject: ["threads": rows, "total": 2, "nextOffset": 2]), as: UTF8.self)
                }
                else if path.hasPrefix("/api/threads/thread/history") {
                    body = #"{"thread":{"id":"thread"},"timeline":[{"id":"turn","type":"turn","turnId":"t","status":"completed"},{"id":"result","type":"agentMessage","turnId":"t","text":"详情应显示在弹窗中。","phase":"final"}],"controls":{"requests":[]}}"#
                }
                else if path == "/api/notifications/read" {
                    Self.lock.withLock { Self.readThrough = 1 }
                    body = #"{"readThrough":1}"#
                }
                else if path.hasPrefix("/api/projects?") { body = #"{"projects":[{"id":"project","title":"示例项目","total":1}],"total":1,"nextOffset":1}"# }
                else if path.contains("/threads?") { body = #"{"threads":[{"id":"thread","title":"示例会话"}],"total":1,"nextOffset":1}"# }
                else { body = #"{"enabled":false,"total":0,"threads":[]}"# }
            }
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    public override func stopLoading() {}
}
