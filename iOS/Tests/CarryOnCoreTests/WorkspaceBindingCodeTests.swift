import Testing
import Foundation
@testable import CarryOnCore

@Test func bindingCodesAreSeparateFromLoginAndRejectOtherOrigins() throws {
    let suffix = "#carryon-bind=" + String(repeating: "a", count: 32) + "." + String(repeating: "b", count: 43)
    let code = try WorkspaceBindingCode("https://console.test/carryon/" + suffix)
    #expect(code.address.base.absoluteString == "https://console.test/carryon/")
    #expect(code.body["secret"].string == String(repeating: "b", count: 43))
    for prefix in ["http://console.test/", "https://user:pass@console.test/", "https://console.test/?x=1", "file:///tmp/"] {
        #expect(throws: (any Error).self) { try WorkspaceBindingCode(prefix + suffix) }
    }
    #expect(throws: (any Error).self) { try WorkspaceBindingCode("https://console.test/" + suffix.replacingOccurrences(of: "carryon-bind", with: "carryon-login")) }
}

private final class RegistrationProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let registration = request.url!.path.hasSuffix("/register")
        let headers = registration ? ["Set-Cookie":"carryon-console=new-account-session; Path=/console/; Secure; HttpOnly"] : [:]
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!
        let result: JSONValue = .object(["authenticated":.bool(registration),"devices":.array([]),"cookie":.string(request.value(forHTTPHeaderField:"Cookie") ?? "")])
        client?.urlProtocol(self, didReceive:response, cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self, didLoad:try! result.encoded())
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@Test func registrationUsesTheSamePersistableSessionAsLogin() async throws {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [RegistrationProtocol.self]
    let api = ConsoleAPI(address:try ConsoleAddress("https://console.test"), configuration:configuration)
    _ = try await api.request("register", body:.object(["username":.string("alice"),"password":.string("a long password")]))
    #expect(try await api.completeLogin().isEmpty)
    #expect(try await api.request("session")["cookie"].string == "carryon-console=new-account-session")
}
