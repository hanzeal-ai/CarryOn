import Foundation
import Testing
@testable import CarryOnCore

@Test func addressPreservesPrefixAndOrigin() throws {
    let address = try ConsoleAddress(" https://example.com:9443/carryon/ ")
    #expect(address.origin == "https://example.com:9443")
    #expect(try address.socketURL(deviceID: "mac").absoluteString == "wss://example.com:9443/carryon/console/devices/mac/ws")
    #expect(try address.url("devices/mac/request").absoluteString == "https://example.com:9443/carryon/console/devices/mac/request")
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
    let suite = "CarryOn.Tests." + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    let body: JSONValue = .object(["prompt": .string("private prompt")])
    let first = PendingWrites(defaults: defaults)
    let id = try first.requestID(scope: "cloud/device1", target: "thread1", path: "/compose", body: body)
    let restored = PendingWrites(defaults: defaults)
    #expect(try restored.requestID(scope: "cloud/device1", target: "thread1", path: "/compose", body: body) == id)
    #expect(throws: APIError.self) { try restored.requestID(scope: "cloud/device1", target: "thread1", path: "/compose", body: .object(["prompt": .string("changed")])) }
    #expect(try restored.requestID(scope: "cloud/device2", target: "thread1", path: "/compose", body: body) != id)
    let persisted = try #require(defaults.data(forKey: "carryon.pendingWrites.v1"))
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
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: isLogin ? ["Set-Cookie": "carryon-console=fixture-session; Path=/carryon/console/; Secure; HttpOnly"] : [:])!
        let result: JSONValue = status == 200 ? .object([
            "authenticated": .bool(true),
            "devices": .array([]), "account": .object(["id": .string("owner")]),
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
    let api = ConsoleAPI(address: try ConsoleAddress("https://example.com/carryon"), configuration: configuration)
    _ = try await api.request("login", body: .object(["token": .string("test-only")]))
    let session = try await api.request("session")
    #expect(session["origin"].text == "https://example.com")
    #expect(session["cookie"].text == "carryon-console=fixture-session")
    let proxied = try await api.device("mac1", path: "/api/projects")
    #expect(proxied["path"].text == "/carryon/console/devices/mac1/request")
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
    let suite = "CarryOn.Tests." + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    defaults.set(Data("broken".utf8), forKey: "carryon.pendingWrites.v1")
    let pending = PendingWrites(defaults: defaults)
    #expect(throws: APIError.self) { try pending.requestID(scope: "scope", target: "thread", path: "/compose", body: .object([:])) }
}

@Test func outgoingLiveEvidenceIgnoresLateHTTPAndNeverRecreatesConfirmedMessage() {
    let start: JSONValue = .object(["id": .string("r"), "prompt": .string("hello"), "state": .string("sending")])
    let live = OutgoingMessageProjection.merge(start, .object(["state": .string("completed")]), live: true)
    #expect(OutgoingMessageProjection.merge(live, .object(["state": .string("preparing")]))?["state"].text == "completed")
    #expect(OutgoingMessageProjection.merge(nil, .object(["state": .string("preparing")])) == nil)
    #expect(OutgoingMessageProjection.merge(live, .object(["state": .string("acknowledged")]), live: true) == nil)
}

@Test func historyWireAppliesSpliceAndRejectsMissingBase() throws {
    var wire = HistoryWireProjection()
    let initial: JSONValue = .object(["subscription": .string("a"), "threadId": .string("t"), "history": .object([
        "historyRevision": .string("1"), "timeline": .array([.object(["id": .string("a"), "text": .string("old")])]), "obsolete": .bool(true)])])
    _ = try wire.decode(initial)
    let update: JSONValue = .object(["subscription": .string("a"), "threadId": .string("t"), "historyDelta": .object([
        "base": .string("1"), "fields": .object(["historyRevision": .string("2")]), "remove": .array([.string("obsolete")]),
        "start": .number(0), "delete": .number(1), "items": .array([.object(["id": .string("a"), "text": .string("new")])])])])
    let result = try wire.decode(update)
    #expect(result["history"]["timeline"].array.first?["text"].text == "new")
    #expect(result["history"]["obsolete"] == .null)
    #expect(throws: APIError.self) { _ = try wire.decode(update) }
    var fresh = HistoryWireProjection()
    #expect(throws: APIError.self) { _ = try fresh.decode(update) }
}

private final class MemorySessionCredentials: SessionCredentials, @unchecked Sendable {
    private let lock = NSLock()
    private var tokens: [String: String] = [:]
    func load(server: String) throws -> String? { lock.withLock { tokens[server] } }
    func save(_ token: String, server: String) throws { lock.withLock { tokens[server] = token } }
    func remove(server: String) throws { _ = lock.withLock { tokens.removeValue(forKey: server) } }
    func remove(server: String, matching token: String) throws {
        lock.withLock { if tokens[server] == token { tokens.removeValue(forKey: server) } }
    }
}

@Test func savedSessionRestoresOnlyForItsServerAndExpiresOrLogsOut() async throws {
    let vault = MemorySessionCredentials()
    let address = try ConsoleAddress("https://example.com/carryon")
    func client(_ address: ConsoleAddress) -> ConsoleAPI {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [FixtureProtocol.self]
        return ConsoleAPI(address: address, configuration: config, credentials: vault)
    }
    let first = client(address)
    _ = try await first.request("login", body: .object(["token": .string("login-secret")]))
    #expect(try vault.load(server: address.base.absoluteString) == nil)
    _ = try await first.completeLogin()
    #expect(try vault.load(server: address.base.absoluteString) == "fixture-session")
    await first.invalidate() // Closing the process/session must not log out.
    let restored = client(address)
    #expect(try await restored.restoreSession())
    #expect(try await restored.request("session")["cookie"].text == "carryon-console=fixture-session")
    let other = client(try ConsoleAddress("https://example.com/other"))
    #expect(try await !other.restoreSession())
    do { _ = try await restored.request("denied") } catch {}
    #expect(try vault.load(server: address.base.absoluteString) != nil)
    do { _ = try await restored.request("expired") } catch {}
    #expect(try vault.load(server: address.base.absoluteString) == nil)
    _ = try await restored.request("login", body: .object(["token": .string("login-secret")]))
    _ = try await restored.request("logout", method: "POST")
    #expect(try vault.load(server: address.base.absoluteString) == nil)
    await restored.invalidate(); await other.invalidate()
}

@Test @MainActor func definitiveWriteFailureUnlocksChangedContentButUnknownOutcomeDoesNot() throws {
    let suite = "CarryOn.Tests." + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    for state in ["failed", "interrupted", "uncertain", "preparing", "dispatching"] {
        let pending = PendingWrites(defaults: defaults, storageKey: state)
        let body: JSONValue = .object(["prompt": .string("original")])
        let changed: JSONValue = .object(["prompt": .string("edited")])
        let id = try pending.requestID(scope: "scope", target: "thread", path: "/compose", body: body)
        let job: JSONValue = .object(["id": .string(id), "threadId": .string("thread"), "state": .string(state)])
        try pending.reconcile(scope: "scope", job: job.setting("id", .string("other")))
        #expect(throws: APIError.self) { try pending.requestID(scope: "scope", target: "thread", path: "/compose", body: changed) }
        try pending.reconcile(scope: "scope", job: job)
        let restarted = PendingWrites(defaults: defaults, storageKey: state)
        if ["failed", "interrupted"].contains(state) {
            #expect(try restarted.requestID(scope: "scope", target: "thread", path: "/compose", body: changed) != id)
        } else {
            #expect(throws: APIError.self) { try restarted.requestID(scope: "scope", target: "thread", path: "/compose", body: changed) }
        }
    }
}

@Test func composerFollowsPauseAppendRestartContract() {
    #expect(ComposerAction.resolve(text: "", hasImages: false, running: true, interrupted: false) == .pause)
    #expect(ComposerAction.resolve(text: "追加", hasImages: false, running: true, interrupted: false) == .send)
    #expect(ComposerAction.resolve(text: "", hasImages: false, running: false, interrupted: true) == .restart)
    #expect(ComposerAction.resolve(text: "新内容", hasImages: false, running: false, interrupted: true) == .send)
    #expect(ComposerAction.resolve(text: "", hasImages: true, running: false, interrupted: true) == .send)
    #expect(ComposerAction.resolve(text: "  ", hasImages: false, running: false, interrupted: false) == .unavailable)
}

@Test @MainActor func projectCreationReceiptClearsOnlyItsPendingProject() throws {
    let defaults = UserDefaults(suiteName: UUID().uuidString)!
    let writes = PendingWrites(defaults: defaults)
    let body: JSONValue = .object(["projectId": .string("project-a"), "prompt": .string("hello")])
    let id = try writes.requestID(scope: "scope", target: "new:project-a", path: "/api/threads", body: body)
    let other = try writes.requestID(scope: "scope", target: "new:project-b", path: "/api/threads", body: body)
    try writes.reconcile(scope: "scope", job: .object(["id": .string(id), "threadId": .string("controller"),
        "state": .string("completed"), "creationProject": .object(["groupId": .string("project-a")])]))
    #expect(try writes.requestID(scope: "scope", target: "new:project-a", path: "/api/threads", body: body) != id)
    #expect(try writes.requestID(scope: "scope", target: "new:project-b", path: "/api/threads", body: body) == other)
}

@Test func initializationGuidanceMatchesCurrentCloud() throws {
    #expect(try ConsoleAddress(ConsoleAddress.defaultURL).initializationCommand == "carryon init")
    #expect(try ConsoleAddress("https://self-hosted.test/prefix").initializationCommand == "carryon init --url 'https://self-hosted.test/prefix/'")
    #expect(try ConsoleAddress("https://self-hosted.test/team's").initializationCommand == "carryon init --url 'https://self-hosted.test/team'\\''s/'")
}

@Test @MainActor func draftStoreResetPreservesSavedDraftsAndReloads() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let file = directory.appendingPathComponent("drafts.json")
    let store = DraftStore(file: file) { _, _ in Issue.record("Draft persistence failed") }
    await store.load(scope: "account-a")
    store.texts["server\nthread"] = "Pending edit"
    store.images["server\nthread"] = ["attachment"]
    store.reset()
    #expect(store.texts.isEmpty)
    #expect(store.images.isEmpty)
    store.save()
    #expect(try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil).count == 1)
    await store.load(scope: "account-a")
    #expect(store.texts["server\nthread"] == "Pending edit")
    #expect(store.images["server\nthread"] == ["attachment"])
}

@Test @MainActor func failedDraftSaveSurvivesResetAndOtherAccount() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let parent = directory.appendingPathComponent("drafts")
    let store = DraftStore(file: parent.appendingPathComponent("drafts.json")) { _, _ in }
    await store.load(scope: "a")
    store.texts["thread"] = "unsaved"
    store.images["thread"] = ["attachment"]
    try Data().write(to: parent)
    store.reset()
    #expect(store.texts.isEmpty)
    await store.load(scope: "b")
    #expect(store.texts.isEmpty)
    store.reset()
    try FileManager.default.removeItem(at: parent)
    await store.load(scope: "a")
    #expect(store.texts["thread"] == "unsaved")
    #expect(store.images["thread"] == ["attachment"])
    store.reset()
    await store.load(scope: "a")
    #expect(store.texts["thread"] == "unsaved")
}

@Test @MainActor func draftsEditedAfterReadFailureStayRecoverable() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = DraftStore(file: directory.appendingPathComponent("drafts.json")) { _, _ in }
    await store.load(scope: "a")
    store.texts["old"] = "saved"
    store.reset()
    let file = try #require(FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil).first)
    let original = try Data(contentsOf: file)
    try Data("broken".utf8).write(to: file)
    await store.load(scope: "a")
    store.texts["new"] = "pending"
    store.reset()
    #expect(try String(contentsOf: file, encoding: .utf8) == "broken")
    try original.write(to: file)
    await store.load(scope: "a")
    #expect(store.texts["old"] == "saved")
    #expect(store.texts["new"] == "pending")
}

@Test @MainActor func clearingUnreadDraftDoesNotRestoreOldContent() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let store = DraftStore(file: directory.appendingPathComponent("drafts.json")) { _, _ in }
    await store.load(scope: "a")
    store.texts["thread"] = "old"
    store.images["thread"] = ["image"]
    store.reset()
    let file = try #require(FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil).first)
    let original = try Data(contentsOf: file)
    try Data("broken".utf8).write(to: file)
    await store.load(scope: "a")
    store.texts["thread"] = ""
    store.images["thread"] = []
    store.reset()
    try original.write(to: file)
    await store.load(scope: "a")
    #expect(store.texts["thread", default: ""].isEmpty)
    #expect(store.images["thread", default: []].isEmpty)
    store.reset()
    await store.load(scope: "a")
    #expect(store.texts.isEmpty)
    #expect(store.images.isEmpty)
}
