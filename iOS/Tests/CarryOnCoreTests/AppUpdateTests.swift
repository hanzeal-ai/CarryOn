import Foundation
import Testing
@testable import CarryOnCore

private func updateManifest(platform: String = "ios", channel: String = "testflight", version: String = "1.0", build: String = "4",
                            url: String = "https://testflight.apple.com/join/AbCd1234", architecture: String? = nil,
                            identifier: String = "com.hanzeal.carryon", minimum: String = "17.0") throws -> AppUpdateManifest {
    var release: [String: Any] = ["platform": platform, "channel": channel, "bundleIdentifier": identifier,
                               "version": version, "build": build, "minimumSystemVersion": minimum, "url": url, "notes": "更新说明"]
    if let architecture { release["architecture"] = architecture }
    let data = try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "releases": [release]])
    return try JSONDecoder().decode(AppUpdateManifest.self, from: data)
}
private let updateInstalled = try! InstalledAppVersion(version: "1.0", build: "3", bundleIdentifier: "com.hanzeal.carryon")

@Test func updateVersionComparisonIsNumericAndRejectsMalformedVersions() throws {
    #expect(try AppVersion("1.10") > AppVersion("1.9.9"))
    #expect(try AppVersion("1.0") == AppVersion("1.0.0"))
    for invalid in ["", "1..2", "1.2-beta", "1.2.3.4", "-1", "１２", "1234567890"] {
        #expect(throws: AppUpdateError.self) { try AppVersion(invalid) }
    }
}
@Test func updateDetectsTestFlightBuildAndNeverOffersDowngrade() throws {
    let latest = try updateManifest()
    #expect(try latest.result(installed: updateInstalled, platform: .iOS, channel: .testFlight, architecture: "arm64", systemVersion: "17.0") == .available(latest.releases[0]))
    let older = try updateManifest(version: "0.9", build: "999")
    #expect(try older.result(installed: updateInstalled, platform: .iOS, channel: .testFlight, architecture: "arm64", systemVersion: "17.0") == .current)
    #expect(try latest.result(installed: updateInstalled, platform: .iOS, channel: .appStore, architecture: "arm64", systemVersion: "17.0") == .unavailable)
    #expect(try latest.result(installed: updateInstalled, platform: .iOS, channel: .testFlight, architecture: "arm64", systemVersion: "16.0") == .requiresSystem(latest.releases[0]))
}
@Test func updateMatchesMacArchitectureAndOfficialArtifact() throws {
    let manifest = try updateManifest(platform: "macos", channel: "dmg", version: "0.3.0", build: "0.3.0",
        url: "https://github.com/hanzeal-ai/CarryOn/releases/download/v0.3.0/CarryOn-0.3.0-macos-arm64.dmg", architecture: "arm64", identifier: "local.carryon.desktop", minimum: "13.0")
    let current = try InstalledAppVersion(version: "0.2.2", build: "0.2.2", bundleIdentifier: "local.carryon.desktop")
    #expect(try manifest.result(installed: current, platform: .macOS, channel: .dmg, architecture: "arm64", systemVersion: "14.0") == .available(manifest.releases[0]))
    #expect(try manifest.result(installed: current, platform: .macOS, channel: .dmg, architecture: "x86_64", systemVersion: "14.0") == .unavailable)
}
@Test func updateRejectsUnsafeLinksWrongAppAndDuplicateChannels() throws {
    for url in ["http://testflight.apple.com/join/AbCd1234", "https://testflight.apple.com.evil.test/join/AbCd1234", "https://user:secret@testflight.apple.com/join/AbCd1234", "https://testflight.apple.com:8443/join/AbCd1234", "https://testflight.apple.com/join/AbCd1234?redirect=bad"] {
        #expect(throws: AppUpdateError.self) { try updateManifest(url: url).releases[0].validate() }
    }
    let wrong = try updateManifest(identifier: "another.app")
    #expect(throws: AppUpdateError.self) { try wrong.result(installed: updateInstalled, platform: .iOS, channel: .testFlight, architecture: "arm64", systemVersion: "17.0") }
    let good = try updateManifest()
    let duplicate = AppUpdateManifest(schemaVersion: 1, releases: good.releases + good.releases)
    #expect(throws: AppUpdateError.self) { try duplicate.result(installed: updateInstalled, platform: .iOS, channel: .testFlight, architecture: "arm64", systemVersion: "17.0") }
    try updateManifest(channel: "app-store", url: "https://apps.apple.com/cn/app/carryon/id1234567890").releases[0].validate()
}

private final class UpdateProtocol: URLProtocol, @unchecked Sendable {
    struct Reply: Sendable { let status: Int; let body: Data; let length: Int? }
    private static let lock = NSLock()
    nonisolated(unsafe) private static var replies: [String: Reply] = [:]
    nonisolated(unsafe) private static var credentialsSeen = false
    static func client(status: Int = 200, body: Data = Data(), length: Int? = nil) -> AppUpdateClient {
        let id = UUID().uuidString
        lock.withLock { replies[id] = Reply(status: status, body: body, length: length) }
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [Self.self]; config.httpAdditionalHeaders = ["X-Fixture-ID": id]
        return AppUpdateClient(configuration: config)
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let reply = Self.lock.withLock {
            if request.value(forHTTPHeaderField: "Cookie") != nil || request.value(forHTTPHeaderField: "Authorization") != nil { Self.credentialsSeen = true }
            return Self.replies[request.value(forHTTPHeaderField: "X-Fixture-ID") ?? ""]!
        }
        let fields = reply.length.map { ["Content-Length": String($0)] }
        let response = HTTPURLResponse(url: request.url!, statusCode: reply.status, httpVersion: "HTTP/1.1", headerFields: fields)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: reply.body); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
    static var sawCredentials: Bool { lock.withLock { credentialsSeen } }
}
@Test func updateTransportDistinguishesUnpublishedOfflineAndInvalidManifest() async throws {
    #expect(try await UpdateProtocol.client(status: 404).fetch() == nil)
    await #expect(throws: AppUpdateError.self) { try await UpdateProtocol.client(status: 503).fetch() }
    await #expect(throws: AppUpdateError.self) { try await UpdateProtocol.client(body: Data("not JSON".utf8)).fetch() }
    await #expect(throws: AppUpdateError.self) { try await UpdateProtocol.client(length: 128 * 1024 + 1).fetch() }
    await #expect(throws: AppUpdateError.self) { try await UpdateProtocol.client(body: Data(repeating: 32, count: 128 * 1024 + 1)).fetch() }
    let manifest = try await UpdateProtocol.client(body: JSONEncoder().encode(updateManifest())).fetch()
    #expect(manifest?.releases.count == 1)
    #expect(!UpdateProtocol.sawCredentials)
}
