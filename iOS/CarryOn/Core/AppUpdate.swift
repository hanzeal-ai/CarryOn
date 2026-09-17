import Foundation
import Combine

public struct AppUpdateError: LocalizedError, Sendable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

public struct AppVersion: Comparable, Sendable {
    private let parts: [Int]
    public init(_ text: String) throws {
        let values = text.split(separator: ".", omittingEmptySubsequences: false)
        guard (1...3).contains(values.count), values.allSatisfy({ !$0.isEmpty && $0.count <= 9 && $0.allSatisfy({ $0.isASCII && $0.isNumber }) }) else {
            throw AppUpdateError("版本信息格式无效")
        }
        parts = values.map { Int($0)! } + Array(repeating: 0, count: 3 - values.count)
    }
    public static func < (lhs: Self, rhs: Self) -> Bool { lhs.parts.lexicographicallyPrecedes(rhs.parts) }
}

public enum AppUpdatePlatform: String, Codable, Sendable { case iOS = "ios", macOS = "macos" }
public enum AppUpdateChannel: String, Codable, Sendable { case appStore = "app-store", testFlight = "testflight", dmg }

public struct InstalledAppVersion: Sendable {
    public let version: String
    public let build: String
    public let bundleIdentifier: String
    public var label: String { version == build ? version : "\(version) (\(build))" }
    public init(version: String, build: String, bundleIdentifier: String) throws {
        _ = try AppVersion(version); _ = try AppVersion(build)
        guard !bundleIdentifier.isEmpty else { throw AppUpdateError("缺少应用标识") }
        self.version = version; self.build = build; self.bundleIdentifier = bundleIdentifier
    }
    public init(bundle: Bundle = .main) throws {
        guard let version = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
              let build = bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String,
              let identifier = bundle.bundleIdentifier else { throw AppUpdateError("无法读取当前应用版本") }
        try self.init(version: version, build: build, bundleIdentifier: identifier)
    }
}

public struct AppRelease: Codable, Equatable, Sendable {
    public let platform: AppUpdatePlatform
    public let channel: AppUpdateChannel
    public let architecture: String?
    public let bundleIdentifier: String
    public let version: String
    public let build: String
    public let minimumSystemVersion: String
    public let url: URL
    public let notes: String
    public var versionLabel: String { version == build ? version : "\(version) (\(build))" }
    public var actionTitle: String {
        switch channel { case .appStore: "前往 App Store 更新"; case .testFlight: "前往 TestFlight 更新"; case .dmg: "下载安装包" }
    }
    public func validate() throws {
        _ = try AppVersion(version); _ = try AppVersion(build); _ = try AppVersion(minimumSystemVersion)
        guard !bundleIdentifier.isEmpty, notes.count <= 8000, url.scheme == "https", url.user == nil, url.password == nil,
              url.port == nil, url.fragment == nil, url.query == nil else { throw AppUpdateError("更新信息或下载地址无效") }
        switch (platform, channel) {
        case (.iOS, .testFlight):
            guard architecture == nil, url.host == "testflight.apple.com",
                  url.path.range(of: #"^/join/[A-Za-z0-9]{8}/?$"#, options: .regularExpression) != nil else { throw AppUpdateError("TestFlight 更新地址无效") }
        case (.iOS, .appStore):
            guard architecture == nil, url.host == "apps.apple.com",
                  url.path.range(of: #"^/(?:[a-z]{2}/)?app/(?:[^/]+/)?id[0-9]+/?$"#, options: .regularExpression) != nil else { throw AppUpdateError("App Store 更新地址无效") }
        case (.macOS, .dmg):
            guard let architecture, ["arm64", "x86_64"].contains(architecture), url.host == "github.com" else { throw AppUpdateError("Mac 更新架构或地址无效") }
            let prefix = "/hanzeal-ai/CarryOn/releases/download/"
            let suffix = "/CarryOn-\(version)-macos-\(architecture).dmg"
            guard url.path == prefix + "v" + version + suffix || url.path == prefix + version + suffix else { throw AppUpdateError("安装包不属于对应版本的官方发布") }
        default: throw AppUpdateError("此平台不支持指定更新渠道")
        }
    }
}

public enum AppUpdateResult: Equatable, Sendable {
    case unavailable, current, available(AppRelease), requiresSystem(AppRelease)
}
public struct AppUpdateManifest: Codable, Sendable {
    public let schemaVersion: Int
    public let releases: [AppRelease]
    public func result(installed: InstalledAppVersion, platform: AppUpdatePlatform, channel: AppUpdateChannel,
                       architecture: String, systemVersion: String) throws -> AppUpdateResult {
        guard schemaVersion == 1, releases.count <= 8 else { throw AppUpdateError("更新清单版本不受支持") }
        for release in releases { try release.validate() }
        let matches = releases.filter { $0.platform == platform && $0.channel == channel && (platform == .iOS || $0.architecture == architecture) }
        guard matches.count <= 1 else { throw AppUpdateError("更新清单包含重复的发布渠道") }
        guard let release = matches.first else { return .unavailable }
        guard release.bundleIdentifier == installed.bundleIdentifier else { throw AppUpdateError("更新清单与当前应用不匹配") }
        let incoming = try AppVersion(release.version), current = try AppVersion(installed.version)
        let incomingBuild = try AppVersion(release.build), currentBuild = try AppVersion(installed.build)
        guard incoming > current || (incoming == current && incomingBuild > currentBuild) else { return .current }
        if try AppVersion(systemVersion) < AppVersion(release.minimumSystemVersion) { return .requiresSystem(release) }
        return .available(release)
    }
}

private final class AppUpdateRedirects: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        guard let url = request.url, url.scheme == "https", url.user == nil, url.password == nil,
              ["github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"].contains(url.host ?? "") else { completionHandler(nil); return }
        completionHandler(request)
    }
}

public final class AppUpdateClient: Sendable {
    public static let manifestURL = URL(string: "https://github.com/hanzeal-ai/CarryOn/releases/latest/download/app-updates.json")!
    private let session: URLSession
    public init(configuration: URLSessionConfiguration = .ephemeral) {
        configuration.httpCookieStorage = nil; configuration.httpShouldSetCookies = false; configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 15; configuration.timeoutIntervalForResource = 20
        session = URLSession(configuration: configuration, delegate: AppUpdateRedirects(), delegateQueue: nil)
    }
    deinit { session.invalidateAndCancel() }
    public func fetch() async throws -> AppUpdateManifest? {
        var request = URLRequest(url: Self.manifestURL)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("CarryOn-App-Updater", forHTTPHeaderField: "User-Agent")
        let (bytes, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse else { throw AppUpdateError("更新服务响应无效") }
        if response.statusCode == 404 { return nil }
        guard response.statusCode == 200 else { throw AppUpdateError("检查更新失败（HTTP \(response.statusCode)）") }
        guard response.expectedContentLength <= 128 * 1024 else { throw AppUpdateError("更新清单超过大小限制") }
        var data = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard data.count < 128 * 1024 else { throw AppUpdateError("更新清单超过大小限制") }
            data.append(byte)
        }
        do { return try JSONDecoder().decode(AppUpdateManifest.self, from: data) }
        catch { throw AppUpdateError("更新清单格式无效") }
    }
}

@MainActor public final class AppUpdateModel: ObservableObject {
    public enum State: Equatable { case idle, checking, checked(AppUpdateResult), failed(String) }
    @Published public private(set) var state: State = .idle
    public let installed: InstalledAppVersion?
    public let platform: AppUpdatePlatform
    public let channel: AppUpdateChannel
    private let architecture: String
    private let systemVersion: String
    private let client: AppUpdateClient
    public var currentVersion: String { installed?.label ?? "版本未知" }
    public init(platform: AppUpdatePlatform, bundle: Bundle = .main, client: AppUpdateClient = AppUpdateClient()) {
        installed = try? InstalledAppVersion(bundle: bundle); self.platform = platform; self.client = client
        if platform == .macOS { channel = .dmg }
        else if bundle.appStoreReceiptURL?.lastPathComponent == "sandboxReceipt" { channel = .testFlight }
        else {
            #if DEBUG
            channel = .testFlight
            #else
            channel = .appStore
            #endif
        }
        #if arch(arm64)
        architecture = "arm64"
        #else
        architecture = "x86_64"
        #endif
        let os = ProcessInfo.processInfo.operatingSystemVersion
        systemVersion = "\(os.majorVersion).\(os.minorVersion).\(os.patchVersion)"
    }
    public func check() async {
        guard state != .checking else { return }
        guard let installed else { state = .failed("无法读取当前应用版本，请使用正式构建的 App"); return }
        state = .checking
        do {
            let manifest = try await client.fetch()
            try Task.checkCancellation()
            state = .checked(try manifest?.result(installed: installed, platform: platform, channel: channel,
                                                 architecture: architecture, systemVersion: systemVersion) ?? .unavailable)
        } catch is CancellationError { state = .idle }
        catch { state = Task.isCancelled ? .idle : .failed(error.localizedDescription) }
    }
}
