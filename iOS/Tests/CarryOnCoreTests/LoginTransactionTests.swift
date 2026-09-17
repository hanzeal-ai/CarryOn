import Foundation
import Testing
@testable import CarryOnCore

private final class LoginVault: SessionCredentials, @unchecked Sendable {
    private let lock = NSLock()
    private var tokens: [String: String] = [:]
    func load(server: String) throws -> String? { lock.withLock { tokens[server] } }
    func save(_ token: String, server: String) throws { lock.withLock { tokens[server] = token } }
    func remove(server: String) throws { _ = lock.withLock { tokens.removeValue(forKey: server) } }
    func remove(server: String, matching token: String) throws {
        lock.withLock { if tokens[server] == token { tokens.removeValue(forKey: server) } }
    }
}

private final class LoginRequests: @unchecked Sendable {
    private let lock = NSLock()
    private var logouts: [String: String] = [:]
    func record(_ request: URLRequest) {
        lock.withLock { logouts[request.url!.host!] = request.value(forHTTPHeaderField: "Cookie") ?? "" }
    }
    func logoutCookie(_ host: String) -> String? { lock.withLock { logouts[host] } }
}

private final class LoginTransactionProtocol: URLProtocol, @unchecked Sendable {
    static let requests = LoginRequests()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let url = request.url!, host = url.host!
        let authentication = url.path.hasSuffix("/login") || url.path.hasSuffix("/qr/poll")
        let logout = url.path.hasSuffix("/logout")
        if logout { Self.requests.record(request) }
        let sessionFailure = url.path.hasSuffix("/session") && host.hasPrefix("failure-")
        let status = url.path.hasSuffix("/expired") ? 401 : sessionFailure || (logout && host.hasPrefix("revoke-failure-")) ? 503 : 200
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1",
            headerFields: authentication ? ["Set-Cookie": "carryon-console=new-session; Path=/console/; Secure; HttpOnly"] : [:])!
        let directory: JSONValue = host.hasPrefix("malformed-") ? .array([.object([:])]) : .array([])
        let result: JSONValue = .object(["authenticated": .bool(authentication), "devices": directory])
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! result.encoded())
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

private func loginClient(_ prefix: String, vault: LoginVault) throws -> ConsoleAPI {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [LoginTransactionProtocol.self]
    return ConsoleAPI(address: try ConsoleAddress("https://" + prefix + UUID().uuidString.lowercased() + ".test"),
                      configuration: configuration, credentials: vault)
}

@Test func failedDirectoryNeverPersistsNewLoginAndRevokesOnlyNewSession() async throws {
    for prefix in ["failure-", "malformed-"] {
        let vault = LoginVault(), api = try loginClient(prefix, vault: vault)
        let address = await api.address
        let server = address.base.absoluteString
        try vault.save("previous-session", server: server)
        _ = try await api.request("login", body: .object([:]))
        #expect(try vault.load(server: server) == "previous-session")
        await #expect(throws: (any Error).self) { try await api.completeLogin() }
        try await api.cancelLogin()
        #expect(try vault.load(server: server) == "previous-session")
        #expect(LoginTransactionProtocol.requests.logoutCookie(address.base.host!) == "carryon-console=new-session")
    }
}

@Test func qrCancellationRevokesEvenWhenCallingTaskIsCancelled() async throws {
    let vault = LoginVault(), api = try loginClient("qr-", vault: vault)
    let address = await api.address
    _ = try await api.request("qr/poll", body: .object([:]))
    #expect(try vault.load(server: address.base.absoluteString) == nil)
    try await Task {
        withUnsafeCurrentTask { $0?.cancel() }
        try await api.cancelLogin()
    }.value
    #expect(LoginTransactionProtocol.requests.logoutCookie(address.base.host!) == "carryon-console=new-session")
    #expect(try vault.load(server: address.base.absoluteString) == nil)
}

@Test func loginCommitPersistsAndLateCancellationRemovesMatchingCredential() async throws {
    let vault = LoginVault(), api = try loginClient("success-", vault: vault)
    let address = await api.address
    _ = try await api.request("login", body: .object([:]))
    #expect(try vault.load(server: address.base.absoluteString) == nil)
    #expect(try await api.completeLogin().isEmpty)
    #expect(try vault.load(server: address.base.absoluteString) == "new-session")
    try await api.cancelLogin()
    #expect(try vault.load(server: address.base.absoluteString) == nil)
}

@Test func failedServerRevocationIsReportedAndLocalCredentialStillCleared() async throws {
    let vault = LoginVault(), api = try loginClient("revoke-failure-", vault: vault)
    let address = await api.address
    _ = try await api.request("login", body: .object([:]))
    _ = try await api.completeLogin()
    await #expect(throws: APIError.self) { try await api.cancelLogin() }
    #expect(try vault.load(server: address.base.absoluteString) == nil)
}

@Test func staleClientFailureAndLogoutCannotDeleteNewLoginCredential() async throws {
    for route in ["expired", "logout"] {
        let vault = LoginVault(), old = try loginClient("stale-", vault: vault)
        let address = await old.address
        try vault.save("old-session", server: address.base.absoluteString)
        #expect(try await old.restoreSession())
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [LoginTransactionProtocol.self]
        let fresh = ConsoleAPI(address: address, configuration: configuration, credentials: vault)
        _ = try await fresh.request("login", body: .object([:]))
        _ = try await fresh.completeLogin()
        do { _ = try await old.request(route, method: route == "logout" ? "POST" : "GET") }
        catch { #expect((error as? APIError)?.status == 401) }
        #expect(try vault.load(server: address.base.absoluteString) == "new-session")
        await old.invalidate(); await fresh.invalidate()
    }
}

@Test func cancelledInitializationCannotCommitCredential() async throws {
    let vault = LoginVault(), api = try loginClient("cancel-", vault: vault)
    let address = await api.address
    _ = try await api.request("login", body: .object([:]))
    await Task {
        withUnsafeCurrentTask { $0?.cancel() }
        await #expect(throws: (any Error).self) { try await api.completeLogin() }
    }.value
    #expect(try vault.load(server: address.base.absoluteString) == nil)
    try await api.cancelLogin()
}

private final class StalledSessionProtocol: URLProtocol, @unchecked Sendable {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {}
    override func stopLoading() {}
}

@Test func restoreSessionDeadlineCancelsStalledHTTPWithoutDeletingCredential() async throws {
    let vault = LoginVault(), address = try ConsoleAddress("https://startup-deadline.test")
    try vault.save("existing-session", server: address.base.absoluteString)
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [StalledSessionProtocol.self]
    let api = ConsoleAPI(address: address, configuration: configuration, credentials: vault)
    #expect(try await api.restoreSession())
    let clock = ContinuousClock(), start = clock.now
    do {
        _ = try await api.request("session", timeout: 0.05)
        Issue.record("A stalled session check must not hold startup indefinitely")
    } catch {
        #expect((error as? URLError)?.code == .timedOut)
        #expect(start.duration(to: clock.now) < .seconds(2))
    }
    #expect(try vault.load(server: address.base.absoluteString) == "existing-session")
    await api.invalidate()
}
