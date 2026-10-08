import SwiftUI
import CarryOnCore
import Foundation

@main struct ArchivesFixtureApp: App {
    @State private var fixture = ArchivesFixture()
    var body: some Scene {
        WindowGroup {
            Group {
                if fixture.phase == 0 { ArchivedThreadsView() }
                else { ArchiveActionView(thread: fixture.thread, scope: fixture.scope, restoring: fixture.phase == 2) { fixture.completed += 1 }.id(fixture.presentation) }
            }.environment(fixture.model).task { await fixture.run() }
        }
    }
}
private final class ArchiveTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock(); var jobs: [String: [String: Any]] = [:]; var writes = 0; var queries = 0; var archived = true
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? "", body = envelope["body"] as? [String: Any] ?? [:]
            if path.hasPrefix("/api/archived") { return ["threads": archived ? [["id": "fixture", "title": "已归档的项目审查", "cwd": "/workspace/CarryOn"]] : [], "nextOffset": archived ? 1 : 0, "supportsRestore": true] }
            if path.hasSuffix("/archive") || path.hasSuffix("/unarchive") {
                writes += 1; archived = path.hasSuffix("/archive"); let id = body["requestId"] as? String ?? ""
                let result: [String: Any] = ["id": id, "threadId": "fixture", "kind": archived ? "archive" : "unarchive", "state": archived ? "uncertain" : "completed", "result": ["threadId": "fixture", "archived": archived]]
                jobs[id] = result
                if !archived { return ["id": "wrong-receipt", "threadId": "other", "kind": "unarchive", "state": "failed", "error": "wrong job must not clear original ID"] }
                return result
            }
            if path.contains("/api/jobs/") { queries += 1; let id = String(path.split(separator: "/").last!); jobs[id]?["state"] = "completed"; return jobs[id] ?? [:] }
            return [:]
        }
        func counts() -> (Int, Int) { lock.lock(); defer { lock.unlock() }; return (writes, queries) }
    }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var bytes = request.httpBody ?? Data()
        if bytes.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; bytes.append(buffer, count: n) }
        }
        let envelope = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any] ?? [:]
        let data = try! JSONSerialization.data(withJSONObject: Self.store.respond(envelope))
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
@MainActor @Observable private final class ArchivesFixture {
    let model = AppModel(); var phase = 0; var presentation = 0; var completed = 0; var scope = ""; var started = false
    let thread = try! Record(.object(["id": .string("fixture"), "title": .string("已归档的项目审查")]))
    func capture(_ name: String) {
        guard let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent(name + ".png"))
    }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ArchiveTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://archives-fixture.invalid/"), configuration: config))
        model.addressText = "https://archives-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "edit", "send"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true), "supportsArchiving": .bool(true)])
        scope = model.scope
        try? await Task.sleep(for: .seconds(1)); capture("archives")
        model.selectedThread = thread; model.history = .object(["status": .object(["state": .string("idle")]), "runtime": .object(["type": .string("idle")]), "controls": .object(["supportedOperations": .array([.string("archive")])])])
        model.draft = "必须保留的本地草稿"; phase = 1; presentation += 1
        try? await Task.sleep(for: .milliseconds(700))
        model.historySynchronized = false
        NotificationCenter.default.post(name: .init("fixture.archive.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(300))
        let staleHistoryGuard = ArchiveTransport.store.counts().0 == 0 && !model.pending.hasPending(scope: scope, target: "fixture")
        model.historySynchronized = true
        NotificationCenter.default.post(name: .init("fixture.archive.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(700)); capture("archive-unknown")
        let unknownPreserved = completed == 0 && model.selectedThread?.id == "fixture" && ArchiveTransport.store.counts().0 == 1
        phase = 0; try? await Task.sleep(for: .milliseconds(300)); phase = 1; presentation += 1
        try? await Task.sleep(for: .milliseconds(700))
        NotificationCenter.default.post(name: .init("fixture.archive.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(400))
        let reopenedQueryOnly = ArchiveTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.archive.query"), object: nil)
        try? await Task.sleep(for: .milliseconds(700))
        let queryConfirmed = completed == 1 && model.selectedThread == nil && ArchiveTransport.store.counts().0 == 1 && ArchiveTransport.store.counts().1 == 1
        let draftPreserved = model.draftStore.texts[scope + "\nfixture"] == "必须保留的本地草稿"
        model.connected = true; model.historySynchronized = true; phase = 2; presentation += 1
        try? await Task.sleep(for: .milliseconds(700)); capture("archive-restore")
        NotificationCenter.default.post(name: .init("fixture.archive.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(700))
        let malformedFailureRetained = completed == 1 && model.pending.hasPending(scope: scope, target: "fixture") && ArchiveTransport.store.counts().0 == 2
        presentation += 1; try? await Task.sleep(for: .milliseconds(700))
        NotificationCenter.default.post(name: .init("fixture.archive.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(300))
        NotificationCenter.default.post(name: .init("fixture.archive.query"), object: nil)
        try? await Task.sleep(for: .milliseconds(700))
        let restoreNotLoaded = completed == 2 && model.selectedThread == nil && ArchiveTransport.store.counts().0 == 2
        phase = 1; presentation += 1; model.selectedThread = thread; model.historySynchronized = true
        try? await Task.sleep(for: .milliseconds(600)); model.selectedDevice = "other"
        NotificationCenter.default.post(name: .init("fixture.archive.submit"), object: nil)
        try? await Task.sleep(for: .milliseconds(500)); let scopeGuard = ArchiveTransport.store.counts().0 == 2
        let result: [String: Any] = ["passed": malformedFailureRetained && staleHistoryGuard && unknownPreserved && reopenedQueryOnly && queryConfirmed && draftPreserved && restoreNotLoaded && scopeGuard, "malformedFailureRetained": malformedFailureRetained, "staleHistoryGuard": staleHistoryGuard, "unknownPreserved": unknownPreserved, "reopenedQueryOnly": reopenedQueryOnly, "queryConfirmed": queryConfirmed, "draftPreserved": draftPreserved, "restoreNotLoaded": restoreNotLoaded, "scopeGuard": scopeGuard]
        try? JSONSerialization.data(withJSONObject: result).write(to: URL.documentsDirectory.appendingPathComponent("archives-result.json"))
    }
}
