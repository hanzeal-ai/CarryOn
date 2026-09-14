import Foundation

public struct RuntimeLogEntry: Identifiable, Codable, Sendable {
    public var id = UUID()
    public let date: Date
    public let operation: String
    public let workspace: String
    public let message: String
    public let blocking: Bool
}

/// Bounded local diagnostics. Callers classify whether the failed operation needs user action.
public struct RuntimeLog: Sendable {
    public private(set) var entries: [RuntimeLogEntry] = []
    public private(set) var storageFailure: String?
    private let storageURL: URL?
    private var writable = true
    public init(storageURL: URL? = nil) {
        self.storageURL = storageURL
        guard let storageURL else { return }
        do { entries = Array((try LocalFiles.read([RuntimeLogEntry].self, from: storageURL) ?? []).prefix(200)) }
        catch { writable = false; storageFailure = "运行日志无法读取，原文件已保留" }
    }
    private static func redact(_ message: String, secrets: [String]) -> String {
        var result = message
        for secret in secrets where !secret.isEmpty { result = result.replacingOccurrences(of: secret, with: "[已隐藏]") }
        for pattern in [#"(?i)(bearer\s+)[^\s,;]+"#, #"(?i)((?:token|password|cookie|authorization|carryon-console)["']?\s*[=:]\s*["']?)[^\s,;"']+"#] {
            result = result.replacingOccurrences(of: pattern, with: "$1[已隐藏]", options: .regularExpression)
        }
        return String(result.prefix(2048))
    }

    @discardableResult public mutating func record(_ error: Error, operation: String, workspace: String,
                                                   blocking: Bool, date: Date = Date(), secrets: [String] = []) -> Bool {
        let native = error as NSError
        guard !(error is CancellationError), !(native.domain == NSURLErrorDomain && native.code == NSURLErrorCancelled) else { return false }
        let requiresAction = blocking || (error as? APIError)?.status == 401
        entries.insert(RuntimeLogEntry(date: date, operation: operation, workspace: workspace,
                                       message: Self.redact(error.localizedDescription, secrets: secrets), blocking: requiresAction), at: 0)
        if entries.count > 200 { entries.removeLast(entries.count - 200) }
        if let storageURL, writable {
            do { try LocalFiles.write(entries, to: storageURL); storageFailure = nil }
            catch { storageFailure = "运行日志未能保存到本机" }
        }
        return requiresAction
    }
}
