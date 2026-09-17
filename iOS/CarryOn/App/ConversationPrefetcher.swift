import Foundation
import CarryOnCore

/// Reuses the existing delta protocol for a bounded set of running conversations.
@MainActor final class ConversationPrefetcher {
    private var tasks: [String: Task<Void, Never>] = [:]
    private var streams: [String: ConsoleStream] = [:]
    private var lastRunning: [String: Date] = [:]
    private var runningIDs: [String] = []
    private var selectedID: String?
    private var settled: Set<String> = []
    private var scope = ""
    private var generation = UUID()

    func update(ids: [String], selected: String?, scope: String, deviceID: String, client: ConsoleAPI,
                receive: @escaping @MainActor (String, JSONValue) async -> Void) {
        if self.scope != scope { stop(); self.scope = scope }
        runningIDs = ids; selectedID = selected
        let now = Date()
        for id in ids { lastRunning[id] = now }
        // Keep finishing streams ahead of new candidates so the bounded set receives final messages.
        let tail = lastRunning.keys.filter { !ids.contains($0) && !settled.contains($0) && now.timeIntervalSince(lastRunning[$0]!) < 30 }.sorted()
        let desired = Set((tail + ids).filter { $0 != selected }.prefix(3))
        for id in Array(tasks.keys) where !desired.contains(id) {
            tasks.removeValue(forKey: id)?.cancel(); streams.removeValue(forKey: id)?.close()
        }
        lastRunning = lastRunning.filter { desired.contains($0.key) }
        settled.formIntersection(desired)
        let version = generation
        for id in desired where tasks[id] == nil {
            tasks[id] = Task { [weak self] in
                var backoff = 2
                while !Task.isCancelled {
                    guard let self, self.generation == version else { return }
                    var connection: ConsoleStream?
                    do {
                        let stream = try await client.stream(deviceID: deviceID, selection: .object([
                            "threadId": .string(id), "threadIds": .array([]), "historyProtocol": .number(1),
                            "historyLimit": .number(40), "subscription": .string(UUID().uuidString)
                        ]))
                        connection = stream
                        try Task.checkCancellation()
                        self.streams[id] = stream
                        while !Task.isCancelled {
                            let packet = try await stream.next()
                            try Task.checkCancellation()
                            guard self.generation == version else { break }
                            if packet["threadId"].string == id, packet["error"].string == nil, packet["history"].object != nil {
                                let history = packet["history"]
                                await receive(id, history)
                                guard !Task.isCancelled, self.generation == version else { break }
                                if ["idle", "waiting"].contains(history["status"]["state"].text), history["syncing"].bool != true {
                                    self.settled.insert(id)
                                    if !self.runningIDs.contains(id) {
                                        self.update(ids: self.runningIDs, selected: self.selectedID, scope: scope,
                                                    deviceID: deviceID, client: client, receive: receive)
                                    }
                                } else { self.settled.remove(id) }
                                backoff = 2
                            }
                        }
                    } catch { /* The primary stream and directory own user-visible connection errors. */ }
                    connection?.close()
                    guard !Task.isCancelled, self.generation == version else { return }
                    self.streams[id] = nil
                    do { try await Task.sleep(for: .seconds(backoff)) } catch { return }
                    backoff = min(30, backoff * 2)
                }
            }
        }
    }
    func stop() {
        generation = UUID()
        for task in tasks.values { task.cancel() }
        for stream in streams.values { stream.close() }
        tasks = [:]; streams = [:]; lastRunning = [:]; runningIDs = []; selectedID = nil; settled = []; scope = ""
    }
    func exclude(_ id: String) {
        selectedID = id
        tasks.removeValue(forKey: id)?.cancel(); streams.removeValue(forKey: id)?.close()
        lastRunning[id] = nil; settled.remove(id)
    }
}
