import Foundation
import Testing
@testable import ConnectNowCore

@Test func addressPreservesPrefixAndOrigin() throws {
    let address = try ConsoleAddress(" https://example.com:9443/connectnow/ ")
    #expect(address.origin == "https://example.com:9443")
    #expect(try address.socketURL(deviceID: "mac").absoluteString == "wss://example.com:9443/connectnow/console/devices/mac/ws")
    #expect(try address.url("devices/mac/request").absoluteString == "https://example.com:9443/connectnow/console/devices/mac/request")
    #expect(ConsoleAddress.component("folder/name?x=1") == "folder%2Fname%3Fx%3D1")
    #expect(ConsoleAddress.component("019a-b_c") == "019a-b_c")
}
@Test func insecureOrCredentialAddressesAreRejected() {
    for raw in ["http://example.com", "https://user:secret@example.com", "https://example.com?token=secret", "https://example.com/#token", "https://example.com/a/../b", "file:///tmp/x", "https://"] {
        #expect(throws: APIError.self) { try ConsoleAddress(raw) }
    }
}
@Test func structuredApprovalRoundTripsWithoutChangingIdentifier() throws {
    let raw = #"{"id":27,"fingerprint":"abc","decisions":["decline",{"acceptWithExecpolicyAmendment":{"execpolicy_amendment":["git","status"]}}]}"#
    let value = try JSONDecoder().decode(JSONValue.self, from: Data(raw.utf8))
    #expect(value["id"] == .number(27))
    #expect(try JSONDecoder().decode(JSONValue.self, from: value.encoded()) == value)
    #expect(value["missing"].bool == nil)
    #expect(value["missing"].int == nil)
}
@Test func paginationUsesServerTotalAndRejectsMissingContract() throws {
    let value: JSONValue = .object(["projects": .array([.object(["id": .string("p"), "name": .string("Same name")])]), "total": .number(125), "nextOffset": .number(50)])
    let page = try RecordPage(value, key: "projects")
    #expect(page.total == 125)
    #expect(page.records.count == 1)
    #expect(page.nextOffset == 50)
    #expect(throws: APIError.self) { try RecordPage(.object(["projects": .array([])]), key: "projects") }
}
@Test @MainActor func unknownWriteKeepsIDAcrossRestartAndRejectsChangedPayload() throws {
    let suite = "ConnectNow.Tests." + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    let body: JSONValue = .object(["prompt": .string("private prompt")])
    let first = PendingWrites(defaults: defaults)
    let id = try first.requestID(scope: "cloud/device1", target: "thread1", path: "/compose", body: body)
    let restored = PendingWrites(defaults: defaults)
    #expect(try restored.requestID(scope: "cloud/device1", target: "thread1", path: "/compose", body: body) == id)
    #expect(throws: APIError.self) { try restored.requestID(scope: "cloud/device1", target: "thread1", path: "/compose", body: .object(["prompt": .string("changed")])) }
    #expect(try restored.requestID(scope: "cloud/device2", target: "thread1", path: "/compose", body: body) != id)
    let persisted = try #require(defaults.data(forKey: "connectnow.pendingWrites.v1"))
    #expect(!String(decoding: persisted, as: UTF8.self).contains("private prompt"))
    try restored.accepted(scope: "cloud/device1", target: "thread1")
    #expect(try restored.requestID(scope: "cloud/device1", target: "thread1", path: "/compose", body: body) != id)
}

private final class FixtureProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let url = request.url!
        let path = url.path
        let isLogin = path.hasSuffix("/login")
        let status = path.hasSuffix("/expired") ? 401 : path.hasSuffix("/denied") ? 403 : 200
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: isLogin ? ["Set-Cookie": "connectnow-console=fixture-session; Path=/connectnow/console/; Secure; HttpOnly"] : [:])!
        let result: JSONValue = status == 200 ? .object([
            "authenticated": .bool(true),
            "cookie": .string(request.value(forHTTPHeaderField: "Cookie") ?? ""),
            "origin": .string(request.value(forHTTPHeaderField: "Origin") ?? ""),
            "method": .string(request.httpMethod ?? ""),
            "path": .string(path)
        ]) : .object(["error": .string("fixture rejected")])
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! result.encoded())
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
@Test func loginUsesOriginAndIsolatedCookieThenExpires() async throws {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [FixtureProtocol.self]
    let api = ConsoleAPI(address: try ConsoleAddress("https://example.com/connectnow"), configuration: configuration)
    _ = try await api.request("login", body: .object(["token": .string("test-only")]))
    let session = try await api.request("session")
    #expect(session["origin"].text == "https://example.com")
    #expect(session["cookie"].text == "connectnow-console=fixture-session")
    let proxied = try await api.device("mac1", path: "/api/projects")
    #expect(proxied["path"].text == "/connectnow/console/devices/mac1/request")
    #expect(proxied["method"].text == "POST")
    do { _ = try await api.request("denied"); Issue.record("403 must throw") } catch let error as APIError { #expect(error.status == 403) }
    do { _ = try await api.request("expired"); Issue.record("401 must throw") } catch let error as APIError { #expect(error.status == 401) }
    let after = try await api.request("session")
    #expect(after["cookie"].text.isEmpty)
    await api.invalidate()
}

@Test func submittedDraftClearsOnlyCapturedConversationAndPreservesNewEdits() {
    let sent = ConversationDraft(text: "send once", images: ["image1"])
    var drafts = ["device/thread": sent, "device/new": ConversationDraft(text: "other")]
    drafts["device/thread"]?.didSubmit(sent)
    #expect(drafts["device/thread"] == ConversationDraft())
    #expect(drafts["device/new"]?.text == "other")
    var edited = ConversationDraft(text: "next message", images: ["image2"])
    edited.didSubmit(sent)
    #expect(edited == ConversationDraft(text: "next message", images: ["image2"]))
}

@Test @MainActor func corruptedRequestLedgerFailsClosed() throws {
    let suite = "ConnectNow.Tests." + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    defaults.set(Data("broken".utf8), forKey: "connectnow.pendingWrites.v1")
    let pending = PendingWrites(defaults: defaults)
    #expect(throws: APIError.self) { try pending.requestID(scope: "scope", target: "thread", path: "/compose", body: .object([:])) }
}
