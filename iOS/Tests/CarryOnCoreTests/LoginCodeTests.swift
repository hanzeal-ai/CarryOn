import Testing
import Foundation
@testable import CarryOnCore

@Test func loginCodesBindToHTTPSConsoleAndValidateSecrets() throws {
    let suffix = "#carryon-login=" + String(repeating: "a", count: 32) + "." + String(repeating: "b", count: 43)
    let code = try LoginCode("https://console.test/carryon/" + suffix)
    #expect(code.address.base.absoluteString == "https://console.test/carryon/")
    #expect(code.id == String(repeating: "a", count: 32))
    for prefix in ["http://console.test/", "https://user:pass@console.test/", "https://console.test/?x=1", "file:///tmp/"] {
        #expect(throws: (any Error).self) { try LoginCode(prefix + suffix) }
    }
    for raw in ["https://console.test/", "https://console.test/#token=secret", "https://console.test/#carryon-login=a.b"] {
        #expect(throws: (any Error).self) { try LoginCode(raw) }
    }
}

private final class QRProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let poll = request.url!.path.hasSuffix("/qr/poll")
        let headers = poll ? ["Set-Cookie": "carryon-console=qr-session; Path=/console/; Secure; HttpOnly"] : [:]
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!
        let result: JSONValue = .object(["authenticated": .bool(poll), "cookie": .string(request.value(forHTTPHeaderField: "Cookie") ?? "")])
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! result.encoded())
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}

@Test func qrApprovalInstallsTheSameCookieUsedByAccountLogin() async throws {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [QRProtocol.self]
    let api = ConsoleAPI(address: try ConsoleAddress("https://console.test"), configuration: config)
    _ = try await api.request("qr/claim", body: .object([:]))
    #expect(try await api.request("session")["cookie"].string == "")
    _ = try await api.request("qr/poll", body: .object([:]))
    #expect(try await api.request("session")["cookie"].string == "carryon-console=qr-session")
}
