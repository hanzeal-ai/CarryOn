import SwiftUI
import CarryOnCore

@main struct SectionRegressionApp: App {
    @State private var fixture = SectionFixture()
    var body: some Scene { WindowGroup {
        Text("分组回归").sheet(isPresented: $fixture.show) {
            SectionConversationView(thread: fixture.thread, scope: fixture.scope).id(fixture.presentation)
        }.sheet(isPresented: $fixture.browse) { NativeSectionsView() }.sheet(isPresented: $fixture.manage) { SectionManagementView(section: fixture.editGroup ? fixture.group : nil, scope: fixture.scope, completed: { fixture.managementCompletions += 1 }, movingThread: fixture.ordering ? fixture.thread : nil).id(fixture.presentation) }.environment(fixture.model).onReceive(NotificationCenter.default.publisher(for: .init("fixture.sections.snapshot"))) { note in fixture.snapshot = note.object as? [String: Any] ?? [:] }.onReceive(NotificationCenter.default.publisher(for: .init("fixture.sections.browse.snapshot"))) { note in fixture.browseSnapshot = note.object as? [String: Any] ?? [:] }.task { await fixture.run() }
    } }
}
private final class SectionTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    final class Store: @unchecked Sendable {
        let lock = NSLock(); var writes = 0, queries = 0, sectionReads = 0, managementWrites = 0, managementQueries = 0, jobs: [String: [String: Any]] = [:]
        func respond(_ envelope: [String: Any]) -> [String: Any] {
            lock.lock(); defer { lock.unlock() }
            let path = envelope["path"] as? String ?? "", body = envelope["body"] as? [String: Any] ?? [:]
            if (path == "/api/sections" || path == "/api/sections/custom"), envelope["method"] as? String == "POST" {
                managementWrites += 1; let id = body["requestId"] as! String, action = body["action"] as? String ?? "create"
                var original = body; original.removeValue(forKey: "requestId")
                let sectionID: Any = action == "create" ? NSNull() : "custom" as Any
                let result: [String: Any]
                if action == "order" { result = ["threadId": body["threadId"]!, "sectionId": "custom", "beforeThreadId": body["beforeThreadId"]!] }
                else if action == "delete" { result = ["sectionId": "custom", "deleted": true] }
                else { result = ["section": ["id": "custom", "name": body["name"] as? String ?? ""]] }
                let job: [String: Any] = ["id": id, "threadId": action == "order" ? body["threadId"]! : action == "create" ? "sections" : "custom", "kind": "section-" + action, "sectionId": sectionID, "body": original, "state": action == "create" ? "uncertain" : "completed", "result": result]
                jobs[id] = job
                if action == "create" { return ["id": "wrong", "state": "failed"] }
                if action == "order" { var invalid = job; invalid["result"] = ["threadId": body["threadId"]!, "sectionId": "custom", "beforeThreadId": "wrong"]; return invalid }; return job
            }
            if path.hasPrefix("/api/sections/custom/threads?") { return ["threads": [["id": "fixture", "title": "排序会话"], ["id": "other", "title": "参照会话"]], "nextCursor": NSNull()] }
            if path.hasPrefix("/api/sections?") { sectionReads += 1; return ["sections": [["id": "pinned", "title": "Pinned", "pinned": true], ["id": "custom", "title": "研发"]], "nextCursor": NSNull()] }
            if path.hasSuffix("/section"), envelope["method"] as? String != "POST" { return ["threadId": "fixture", "sectionId": NSNull()] }
            if path.hasSuffix("/section") {
                writes += 1; let id = body["requestId"] as! String, destination = body["sectionId"] as! String
                jobs[id] = ["id": id, "threadId": "fixture", "kind": "section-move", "sectionId": destination, "state": "uncertain", "result": ["threadId": "fixture", "sectionId": destination]]
                return ["id": "wrong-receipt", "threadId": "other", "kind": "section-move", "sectionId": destination, "state": "failed"]
            }
            if path == "/api/jobs" { return ["jobs": []] }
            if path.hasPrefix("/api/jobs/") {
                queries += 1; let id = String(path.split(separator: "/").last!)
                if (jobs[id]?["kind"] as? String)?.hasPrefix("section-") == true, jobs[id]?["kind"] as? String != "section-move" {
                    managementQueries += 1; var job = jobs[id]!
                    if managementQueries == 1 { job["body"] = ["name": "错误名称"]; job["state"] = "failed" }
                    else { job["state"] = "completed" }; return job
                }
                if queries == 1 { return [:] }
                if queries == 3 || queries == 4 { return ["id": id, "threadId": "fixture", "kind": "section-move", "sectionId": "wrong", "state": queries == 3 ? "failed" : "completed", "result": ["threadId": "fixture", "sectionId": "pinned"]] }
                if queries >= 5 { jobs[id]?["state"] = "completed" }; return jobs[id] ?? [:]
            }
            return [:]
        }
        func managementCount() -> Int { lock.lock(); defer { lock.unlock() }; return managementWrites }
        func readCount() -> Int { lock.lock(); defer { lock.unlock() }; return sectionReads }
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
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: Self.store.respond(envelope))); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
@MainActor @Observable private final class SectionFixture {
    @ObservationIgnored var snapshot: [String: Any] = [:]
    @ObservationIgnored var browseSnapshot: [String: Any] = [:]
    var browse = false
    var manage = false
    var editGroup = false
    var ordering = false
    var managementCompletions = 0
    let group = try! Record(.object(["id": .string("custom"), "title": .string("研发")]))
    let model = AppModel(); var show = false; var started = false; var presentation = 0; var scope = ""
    let thread = try! Record(.object(["id": .string("fixture"), "title": .string("旧名称")]))
    func wait() async { try? await Task.sleep(for: .milliseconds(650)) }
    func waitUntilReady() async {
        for _ in 0..<60 {
            NotificationCenter.default.post(name: .init("fixture.sections.inspect"), object: nil)
            if snapshot["loaded"] as? Bool == true, snapshot["busy"] as? Bool == false { return }
            try? await Task.sleep(for: .milliseconds(50))
        }
    }
    func capture(_ file: String = "sections.png") {
        guard let window = (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        try? image.pngData()?.write(to: URL.documentsDirectory.appendingPathComponent(file))
    }
    func run() async {
        guard !started else { return }; started = true
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [SectionTransport.self]
        model.fixtureClient(ConsoleAPI(address: try! ConsoleAddress("https://sections-fixture.invalid/"), configuration: config))
        model.addressText = "https://sections-fixture.invalid/"; model.selectedDevice = "fixture"
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "edit", "send"].map(JSONValue.string))]))]
        model.authenticated = true; model.connected = true; model.historySynchronized = true; model.selectedThread = thread
        model.status = .object(["enabled": .bool(true), "remoteControl": .bool(true), "supportsThreadSections": .bool(true)])
        model.history = .object(["thread": thread.value, "status": .object(["state": .string("idle")]), "runtime": .object(["type": .string("idle")]), "controls": .object(["supportedOperations": .array([])])])
        model.draft = "保留本地草稿"; scope = model.scope
        for id in (try? model.pending.requestIDs(scope: scope, target: thread.id)) ?? [] { try? model.pending.resolve(scope: scope, target: thread.id, requestID: id) }
        show = true; await wait(); await waitUntilReady()
        NotificationCenter.default.post(name: .init("fixture.sections.inspect"), object: nil)
        let initialState = snapshot
        NotificationCenter.default.post(name: .init("fixture.sections.destination"), object: "pinned")
        model.historySynchronized = false
        NotificationCenter.default.post(name: .init("fixture.sections.save"), object: nil); await wait()
        let unsynced = SectionTransport.store.counts().0 == 1 && model.pending.hasPending(scope: scope, target: thread.id)
        let malformedFailure = SectionTransport.store.counts().0 == 1 && model.pending.hasPending(scope: scope, target: thread.id)
        show = false; await wait(); presentation += 1; show = true; await wait(); capture()
        NotificationCenter.default.post(name: .init("fixture.sections.destination"), object: "wrong")
        NotificationCenter.default.post(name: .init("fixture.sections.save"), object: nil); await wait()
        let queryOnly = SectionTransport.store.counts().0 == 1 && SectionTransport.store.counts().1 == 1
        NotificationCenter.default.post(name: .init("fixture.sections.restore"), object: nil); await wait(); capture()
        NotificationCenter.default.post(name: .init("fixture.sections.query"), object: nil); await wait()
        let wrongQueryPreserved = model.pending.hasPending(scope: scope, target: thread.id)
        NotificationCenter.default.post(name: .init("fixture.sections.query"), object: nil); await wait()
        let wrongDestinationSuccessPreserved = model.pending.hasPending(scope: scope, target: thread.id)
        NotificationCenter.default.post(name: .init("fixture.sections.query"), object: nil); await wait()
        let confirmed = model.selectedThread?.title == "旧名称" && model.workspaceRevision > 0 && !model.pending.hasPending(scope: scope, target: thread.id) && SectionTransport.store.counts().0 == 1
        let draftPreserved = model.draft == "保留本地草稿"
        show = false; await wait(); presentation += 1; show = true; await wait(); model.selectedDevice = "other"
        NotificationCenter.default.post(name: .init("fixture.sections.save"), object: nil); await wait()
        let staleScope = SectionTransport.store.counts().0 == 1
        NotificationCenter.default.post(name: .init("fixture.sections.inspect"), object: nil)
        try? JSONSerialization.data(withJSONObject: ["initial": initialState, "final": snapshot, "writes": SectionTransport.store.counts().0, "queries": SectionTransport.store.counts().1, "error": model.error ?? ""]).write(to: URL.documentsDirectory.appendingPathComponent("sections-diagnostic.json"))
        show = false; model.selectedDevice = "fixture"; browse = true; await wait()
        NotificationCenter.default.post(name: .init("fixture.sections.browse.inspect"), object: nil)
        let browseLoaded = browseSnapshot["rows"] as? Int == 2
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array([])]))]
        await wait(); NotificationCenter.default.post(name: .init("fixture.sections.browse.inspect"), object: nil)
        let revokedRowsCleared = browseSnapshot["rows"] as? Int == 0
        browse = false; await wait()
        model.devices = [try! Record(.object(["id": .string("fixture"), "online": .bool(true), "permissions": .array(["view", "edit"].map(JSONValue.string))]))]
        browse = true; await wait(); let readsBeforeSwitch = SectionTransport.store.readCount()
        model.selectedDevice = "other"; await wait()
        let scopeChangeNoRead = SectionTransport.store.readCount() == readsBeforeSwitch
        browse = false; model.selectedDevice = "fixture"; await wait()
        for id in (try? model.pending.requestIDs(scope: scope, target: "sections")) ?? [] { try? model.pending.resolve(scope: scope, target: "sections", requestID: id) }
        manage = true; presentation += 1; await wait()
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.name"), object: "新分组")
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.save"), object: nil); await wait()
        let managementUnknownRetained = SectionTransport.store.managementCount() == 1 && model.pending.hasPending(scope: scope, target: "sections")
        manage = false; await wait(); presentation += 1; manage = true; await wait(); capture("section-management.png")
        let managementWrongBodyRetained = model.pending.hasPending(scope: scope, target: "sections") && SectionTransport.store.managementCount() == 1
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.query"), object: nil); await wait()
        let managementConfirmed = !model.pending.hasPending(scope: scope, target: "sections") && managementCompletions == 1
        manage = false; editGroup = true; presentation += 1; await wait(); manage = true; await wait()
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.name"), object: "研发二组")
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.save"), object: nil); await wait()
        let managementUpdated = SectionTransport.store.managementCount() == 2 && managementCompletions == 2
        manage = false; presentation += 1; await wait(); manage = true; await wait()
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.delete"), object: nil); await wait()
        let managementDeleted = SectionTransport.store.managementCount() == 3 && managementCompletions == 3
        manage = false; ordering = true; presentation += 1; await wait(); manage = true; await wait()
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.before"), object: "other")
        capture("section-order.png")
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.save"), object: nil); await wait()
        let orderingWrongPositionRetained = SectionTransport.store.managementCount() == 4 && model.pending.hasPending(scope: scope, target: "sections")
        NotificationCenter.default.post(name: .init("fixture.sectionManagement.query"), object: nil); await wait()
        let orderingConfirmed = managementCompletions == 4 && !model.pending.hasPending(scope: scope, target: "sections")
        let checks = ["orderingWrongPositionRetained": orderingWrongPositionRetained, "orderingConfirmed": orderingConfirmed, "managementUnknownRetained": managementUnknownRetained, "managementWrongBodyRetained": managementWrongBodyRetained, "managementConfirmed": managementConfirmed, "managementUpdated": managementUpdated, "managementDeleted": managementDeleted, "browseLoaded": browseLoaded, "revokedRowsCleared": revokedRowsCleared, "scopeChangeNoRead": scopeChangeNoRead, "unsynced": unsynced, "malformedFailure": malformedFailure, "reopenedQueryOnly": queryOnly, "wrongQueryPreserved": wrongQueryPreserved, "wrongDestinationSuccessPreserved": wrongDestinationSuccessPreserved, "confirmed": confirmed, "draftPreserved": draftPreserved, "staleScope": staleScope]
        try? JSONSerialization.data(withJSONObject: ["passed": checks.values.allSatisfy { $0 }, "checks": checks]).write(to: URL.documentsDirectory.appendingPathComponent("sections-result.json"))
    }
}
