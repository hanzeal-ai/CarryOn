import Foundation
import Testing
@testable import CarryOnCore

private final class UncertainWriteProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url!.lastPathComponent
        let body = path == "malformed" ? "invalid JSON" : path == "definite" ? "{\"error\":\"conflict\"}" : "{\"error\":\"unknown outcome\",\"uncertain\":true}"
        let response = HTTPURLResponse(url: request.url!, statusCode: 409, httpVersion: nil,
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@Test @MainActor func uncertainHTTPReplyPreservesPendingIdentityAcrossReload() async throws {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [UncertainWriteProtocol.self]
    let api = ConsoleAPI(address: try ConsoleAddress("https://uncertain.test"), configuration: configuration)
    let name = "uncertain-write-" + UUID().uuidString
    let defaults = UserDefaults(suiteName: name)!
    defer { defaults.removePersistentDomain(forName: name) }
    let pending = PendingWrites(defaults: defaults)
    let body: JSONValue = .object(["prompt": .string("hello")])
    let original = try pending.requestID(scope: "scope", target: "thread", path: "/compose", body: body)
    for route in ["uncertain", "malformed", "definite"] {
        do {
            _ = try await api.request(route, body: body)
            Issue.record("Expected HTTP conflict")
        } catch let error as APIError {
            #expect(error.status == 409)
            #expect(error.isWriteRejection == (route == "definite"))
            if error.isWriteRejection { try pending.resolve(scope: "scope", target: "thread", requestID: original) }
        }
        let restored = PendingWrites(defaults: defaults)
        let next = try restored.requestID(scope: "scope", target: "thread", path: "/compose", body: body)
        #expect((next == original) == (route != "definite"))
    }
}
