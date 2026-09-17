import Foundation

public final class AppUpdateFixtureProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var responseMode = "available"
    public static var mode: String {
        get { lock.withLock { responseMode } }
        set { lock.withLock { responseMode = newValue } }
    }
    public static var configuration: URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [Self.self]; return config
    }
    public override class func canInit(with request: URLRequest) -> Bool { true }
    public override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    public override func startLoading() {
        let mode = Self.mode
        let version = mode == "current" ? "0.2.2" : "0.3.0"
        let release: [String: Any] = ["platform": "macos", "channel": "dmg", "architecture": "arm64", "bundleIdentifier": "local.carryon.desktop",
            "version": version, "build": version, "minimumSystemVersion": mode == "incompatible" ? "99.0" : "13.0",
            "url": "https://github.com/hanzeal-ai/CarryOn/releases/download/v\(version)/CarryOn-\(version)-macos-arm64.dmg",
            "notes": "改善会话加载体验，修复工作区切换问题。"]
        let ios: [String: Any] = ["platform": "ios", "channel": "testflight", "bundleIdentifier": "com.hanzeal.carryon",
            "version": mode == "current" ? "1.0" : "1.1", "build": mode == "current" ? "3" : "4", "minimumSystemVersion": mode == "incompatible" ? "99.0" : "17.0",
            "url": "https://testflight.apple.com/join/AbCd1234", "notes": "改善会话加载体验，修复工作区切换问题。"]
        let body = try! JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "releases": [release, ios]])
        let response = HTTPURLResponse(url: request.url!, statusCode: mode == "unpublished" ? 404 : mode == "failure" ? 503 : 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body); client?.urlProtocolDidFinishLoading(self)
    }
    public override func stopLoading() {}
}
