import SwiftUI
import ConnectNowCore

@MainActor @Observable final class AppModel {
    var addressText = UserDefaults.standard.string(forKey: "connectnow.server") ?? ""
    var credential = ""
    var authenticated = false
    var busy = false
    var error: String?
    var devices: [Record] = []
    var selectedDevice = ""
    var status: JSONValue = .null
    var connected = false
    var selectedThread: Record?
    var selectedProject: Record?
    var activityCount: Int?
    var history: JSONValue = .null
    var historyFailure: String?
    var historyCache = DisplayHistoryCache()
    var outgoing: [String: JSONValue] = [:]
    var readSequence = 0
    var historyRevision = 0
    var historyLimit = 40
    var workspaceRevision = 0
    var requests: [Record] = []
    var requestHistory: [Record] = []
    var requestHistoryError: String?
    var drafts: [String: String] = [:]
    var attachments: [String: [String]] = [:]
    var foreground = true
    var writing = false
    var notice: String?
    private(set) var removingDevice = false
    private(set) var epoch = UUID()
    private var api: ConsoleAPI?
    private var updates: Task<Void, Never>?
    private var liveStream: ConsoleStream?
    private var selectionUpdate: Task<Void, Never>?
    private var directoryVersion = 0
    private var directoryUpdates: Task<Void, Never>?
    private let pending = PendingWrites()

    var activityBadgeCount: Int { authenticated ? max(0, activityCount ?? 0) + requests.count : 0 }
    var device: Record? { devices.first { $0.id == selectedDevice } }
    var canWrite: Bool { !removingDevice && authenticated && foreground && connected && status["enabled"].bool == true && status["remoteControl"].bool == true && !writing }
    var state: String { connected ? history["status"]["state"].text : "unknown" }
    var scope: String { addressText + "\n" + selectedDevice }
    var connectionLabel: String {
        if device == nil { return "未选择工作区" }
        if device?.value["online"].bool != true { return "离线" }
        if !connected { return "连接中" }
        if status["enabled"].bool != true { return "Codex 未就绪" }
        return status["remoteControl"].bool == true ? "在线" : "在线 · 只读"
    }
    var draft: String {
        get { drafts[scope + "\n" + (selectedThread?.id ?? "new")] ?? "" }
        set { drafts[scope + "\n" + (selectedThread?.id ?? "new")] = newValue }
    }
    var draftImages: [String] {
        get { attachments[scope + "\n" + (selectedThread?.id ?? "new")] ?? [] }
        set { attachments[scope + "\n" + (selectedThread?.id ?? "new")] = newValue }
    }

    func login() async {
        guard !busy else { return }
        busy = true; error = nil
        defer { busy = false }
        do {
            let address = try ConsoleAddress(addressText)
            let client = ConsoleAPI(address: address)
            _ = try await client.request("login", body: .object(["token": .string(credential.trimmingCharacters(in: .whitespacesAndNewlines))]))
            let session = try await client.request("session")
            guard case .array(let values) = session["devices"] else { throw APIError("设备目录格式不正确") }
            api = client; devices = try values.map(Record.init); credential = ""
            addressText = address.base.absoluteString
            UserDefaults.standard.set(addressText, forKey: "connectnow.server")
            authenticated = true
            switchDevice(devices.first?.id ?? "")
        } catch { report(error) }
    }
    func report(_ failure: Error) {
        guard !Task.isCancelled, !(failure is CancellationError) else { return }
        if (failure as? APIError)?.status == 401 { resetSession() }
        error = failure.localizedDescription
    }
    private func resetSession() {
        epoch = UUID(); updates?.cancel(); selectionUpdate?.cancel(); liveStream?.close(); liveStream = nil; directoryUpdates?.cancel()
        let previous = api; api = nil
        Task { await previous?.invalidate() }
        authenticated = false; connected = false; status = .null; history = .null; historyFailure = nil
        devices = []; selectedDevice = ""; selectedThread = nil; selectedProject = nil; activityCount = nil; requests = []; requestHistory = []; requestHistoryError = nil; drafts = [:]; attachments = [:]; historyCache.clear(); outgoing = [:]; credential = ""
    }
    func logout() async {
        guard let api else { return }
        do { _ = try await api.request("logout", method: "POST"); resetSession() }
        catch { report(error) }
    }
    func switchDevice(_ id: String) {
        epoch = UUID(); updates?.cancel(); selectionUpdate?.cancel(); liveStream?.close(); liveStream = nil; directoryUpdates?.cancel()
        selectedDevice = id; selectedThread = nil; selectedProject = nil; activityCount = nil; history = .null; historyFailure = nil; status = .null
        connected = false; readSequence = 0; workspaceRevision += 1
        startUpdates()
    }
    func removeDevice(_ id: String) async throws {
        guard !removingDevice, devices.contains(where: { $0.id == id }) else { throw APIError("请先选择工作区") }
        removingDevice = true
        updates?.cancel(); directoryUpdates?.cancel()
        defer {
            removingDevice = false
            if authenticated && foreground { startUpdates() }
        }
        let result = try await console("devices/" + ConsoleAddress.component(id), method: "DELETE")
        guard result["removed"].bool == true else { throw APIError("未确认设备已移除，请刷新设备列表核对") }
        devices.removeAll { $0.id == id }
        if selectedDevice == id { switchDevice(devices.first?.id ?? "") }
    }
    func open(_ thread: Record) {
        historyLimit = 40; historyFailure = nil
        selectedThread = thread; history = historyCache.get(scope + "\n" + thread.id) ?? .null; readSequence = 0
        connected = false
        updateSelection()
    }
    func retryHistory() { historyFailure = nil; updateSelection() }
    func loadEarlierHistory() {
        historyLimit = min(100000, historyLimit + 40)
        updateSelection()
    }
    func closeThread() {
        selectedThread = nil; history = .null; historyFailure = nil; readSequence = 0
        updateSelection()
    }
    func setForeground(_ active: Bool) {
        foreground = active
        updates?.cancel(); selectionUpdate?.cancel(); liveStream?.close(); liveStream = nil; directoryUpdates?.cancel(); connected = false
        if active && authenticated { startUpdates() }
    }
    func console(_ route: String, body: JSONValue? = nil, method: String? = nil) async throws -> JSONValue {
        guard let api else { throw APIError("请先登录") }
        let version = epoch
        let value = try await api.request(route, body: body, method: method)
        guard version == epoch, !Task.isCancelled else { throw CancellationError() }
        return value
    }
    func deviceRequest(_ path: String, body: JSONValue? = nil) async throws -> JSONValue {
        guard let api, !selectedDevice.isEmpty else { throw APIError("请先选择工作区") }
        let version = epoch, id = selectedDevice
        let value = try await api.device(id, path: path, body: body)
        guard version == epoch, id == selectedDevice, !Task.isCancelled else { throw CancellationError() }
        return value
    }
    func page(_ path: String, key: String) async throws -> RecordPage {
        try RecordPage(await deviceRequest(path), key: key)
    }
    func refreshDirectory() async throws {
        directoryVersion += 1
        let version = directoryVersion
        do {
        let session = try await console("session")
        guard version == directoryVersion else { return }
        guard case .array(let values) = session["devices"] else { throw APIError("设备目录格式不正确") }
        devices = try values.map(Record.init)
        if !devices.contains(where: { $0.id == selectedDevice }) { switchDevice(devices.first?.id ?? "") }
        let result = try await console("link/pending")
        guard version == directoryVersion else { return }
        guard case .array(let values) = result["requests"] else { throw APIError("连接申请格式不正确") }
        requests = try values.map(Record.init)
        requestHistory = try result["history"].array.map(Record.init)
        requestHistoryError = result["historyError"].string
        if connected && status["enabled"].bool == true && !selectedDevice.isEmpty {
            let activity = try await deviceRequest("/api/activity?limit=1")
            if version == directoryVersion { activityCount = activity["total"].int }
        }
        } catch {
            if version == directoryVersion { throw error }
        }
    }
    private func startUpdates() {
        guard !removingDevice else { return }
        startStream()
        directoryUpdates = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                do { try await self.refreshDirectory() }
                catch { if Task.isCancelled { return }; self.report(error) }
                do { try await Task.sleep(for: .seconds(5)) } catch { return }
            }
        }
    }
    private func selection(_ threadID: String?) -> JSONValue {
        .object(["threadId": threadID.map(JSONValue.string) ?? .null,
                 "threadIds": .array([]), "historyProtocol": .number(1), "historyLimit": .number(Double(historyLimit)), "subscription": .string(UUID().uuidString)])
    }
    private func updateSelection() {
        connected = false
        guard let connection = liveStream, connection.canResubscribe else {
            updates?.cancel(); liveStream?.close(); liveStream = nil; startStream(); return
        }
        let previous = selectionUpdate, generation = epoch, threadID = selectedThread?.id, limit = historyLimit
        selectionUpdate = Task { [weak self] in
            await previous?.value
            guard let self, self.epoch == generation, self.selectedThread?.id == threadID, self.historyLimit == limit,
                  self.liveStream === connection else { return }
            do { try await connection.resubscribe(self.selection(threadID)) }
            catch { connection.close(); self.report(error) }
        }
    }
    private func startStream() {
        guard !removingDevice, foreground, let client = api, !selectedDevice.isEmpty else { return }
        let generation = epoch, deviceID = selectedDevice
        updates = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self.epoch == generation else { return }
                var stream: ConsoleStream?
                do {
                    let connection = try await client.stream(deviceID: deviceID, selection: self.selection(self.selectedThread?.id))
                    stream = connection
                    try Task.checkCancellation()
                    self.liveStream = connection
                    while !Task.isCancelled {
                        let packet = try await connection.next()
                        try Task.checkCancellation()
                        guard self.epoch == generation else { break }
                        guard packet["threadId"].string == self.selectedThread?.id else { continue }
                        self.apply(packet, threadID: self.selectedThread?.id)
                    }
                } catch {
                    if !Task.isCancelled && self.epoch == generation {
                        self.connected = false
                        var failure = error
                        if (error as? APIError)?.status != 401 {
                            do { _ = try await client.request("session") }
                            catch { if (error as? APIError)?.status == 401 { failure = error } }
                        }
                        guard !Task.isCancelled, self.epoch == generation else { stream?.close(); return }
                        self.report(failure)
                    }
                }
                stream?.close()
                if self.liveStream === stream { self.liveStream = nil }
                if Task.isCancelled || self.epoch != generation { return }
                do { try await Task.sleep(for: .seconds(2)) } catch { return }
            }
        }
    }
    private func apply(_ packet: JSONValue, threadID: String?) {
        status = packet["status"]; connected = true
        reconcile(packet["jobs"].array)
        if let revision = packet["workspaceRevision"].int, revision != workspaceRevision { workspaceRevision = revision }
        if packet["error"].string != nil { historyFailure = packet["error"].string; return }
        historyFailure = nil
        if let threadID, packet["threadId"].string == threadID, packet["history"].object != nil {
            let incoming = packet["history"]
            let changed = incoming["historyRevision"].string.map { $0 != history["historyRevision"].string } ?? (incoming != history)
            let sequence = packet["readSequence"].int ?? 0
            if changed { history = incoming; historyCache.set(scope + "\n" + threadID, history) }
            reconcileOutgoing()
            if changed || sequence != readSequence { historyRevision += 1 }
            readSequence = sequence
        }
    }
    func markDisplayed(threadID: String, sequence: Int) async {
        guard foreground, selectedThread?.id == threadID, connected, sequence > 0 else { return }
        do { _ = try await deviceRequest("/api/notifications/read", body: .object(["threadId": .string(threadID), "sequence": .number(Double(sequence))])) }
        catch { report(error) }
    }
    @discardableResult func write(path: String, target: String, body: JSONValue) async -> Bool {
        guard canWrite else { error = "当前连接不可写，请检查本机授权与连接状态"; return false }
        let version = epoch, capturedScope = scope
        writing = true; defer { writing = false }
        do {
            let id = try pending.requestID(scope: capturedScope, target: target, path: path, body: body)
            let composing = path.hasSuffix("/compose")
            if composing {
                outgoing[id] = .object(["id": .string(id), "threadId": .string(target), "scope": .string(capturedScope),
                    "prompt": body["prompt"], "created": .number((Date().timeIntervalSince1970 * 1000).rounded()), "state": .string("sending")])
                historyRevision += 1
            }
            let result: JSONValue
            do { result = try await deviceRequest(path, body: body.setting("requestId", .string(id))) }
            catch {
                if composing, version == epoch, let item = outgoing[id] { outgoing[id] = OutgoingMessageProjection.merge(item, .object(["state": .string("uncertain")])) }
                throw error
            }
            if composing, version == epoch { mergeOutgoing(result.setting("id", .string(id))); reconcileOutgoing() }
            guard version == epoch else { return false }
            let state = result["state"].text
            guard ["preparing", "dispatching", "completed", "accepted", "inProgress"].contains(state) else {
                throw APIError((result["error"].string ?? "操作结果尚未确认") + "；请在请求记录与 Codex App 核对，原请求编号已保留。")
            }
            if ["accepted", "completed", "inProgress"].contains(state) { try pending.accepted(scope: capturedScope, target: target) }
            return true
        } catch { if version == epoch { report(error) }; return false }
    }
    func reconcile(_ jobs: [JSONValue]) {
        for job in jobs { mergeOutgoing(job, live: true) }
        for job in jobs where ["accepted", "completed", "inProgress", "acknowledged"].contains(job["state"].text) {
            try? pending.resolve(scope: scope, target: job["threadId"].text, requestID: job["id"].text)
            try? pending.resolve(scope: scope, target: "new", requestID: job["id"].text)
        }
    }
    var visibleOutgoing: [JSONValue] {
        outgoing.values.filter { $0["scope"].text == scope && $0["threadId"].text == selectedThread?.id }.sorted { ($0["created"].int ?? 0, $0["id"].text) < ($1["created"].int ?? 0, $1["id"].text) }
    }
    private func mergeOutgoing(_ job: JSONValue, live: Bool = false) {
        let id = job["id"].text
        guard let previous = outgoing[id], previous["scope"].text == scope else { return }
        outgoing[id] = OutgoingMessageProjection.merge(previous, job, live: live)
    }
    private func reconcileOutgoing() {
        for item in visibleOutgoing {
            let messageID = item["clientMessageId"].string
            let found = history["timeline"].array.contains { entry in
                guard ["userMessage", "steeringUserMessage"].contains(entry["type"].text) else { return false }
                return (messageID != nil && [entry["nativeId"].string, entry["clientMessageId"].string].contains(messageID)) ||
                    (item["kind"].text == "message" && item["turnId"].string != nil && entry["turnId"] == item["turnId"])
            } || history["queue"]["messages"].array.contains { messageID != nil && $0["id"].string == messageID }
            if found { outgoing.removeValue(forKey: item["id"].text) }
        }
    }
    func confirmJob(_ job: JSONValue) async {
        do {
            if job["state"].text == "uncertain" {
                _ = try await deviceRequest("/api/jobs/\(ConsoleAddress.component(job["id"].text))/acknowledge", body: .object(["confirmed": .bool(true)]))
            }
            try pending.resolve(scope: scope, target: job["threadId"].text, requestID: job["id"].text)
            try pending.resolve(scope: scope, target: "new", requestID: job["id"].text)
        } catch { report(error) }
    }
    func compose(images: [JSONValue] = []) async -> Bool {
        guard let thread = selectedThread else { return false }
        let text = draft
        let capturedKey = scope + "\n" + thread.id
        let sent = ConversationDraft(text: text, images: images.compactMap(\.string))
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !images.isEmpty else { return false }
        var body: JSONValue = .object(["prompt": .string(text)])
        if !images.isEmpty { body = body.setting("images", .array(images)) }
        let success = await write(path: "/api/threads/\(ConsoleAddress.component(thread.id))/compose", target: thread.id, body: body)
        if success {
            var current = ConversationDraft(text: drafts[capturedKey] ?? "", images: attachments[capturedKey] ?? [])
            current.didSubmit(sent)
            drafts[capturedKey] = current.text; attachments[capturedKey] = current.images
        }
        return success
    }
    func answerQuestion(_ question: JSONValue, answer: String, threadID: String) async -> Bool {
        guard selectedThread?.id == threadID, canWrite else { return false }
        let records: JSONValue = .array([.object(["questionItemId": question["id"], "question": question["title"], "answer": .string(answer)])])
        let prompt = "<send_user_message_question_reply>\n" + records.formatted + "\n</send_user_message_question_reply>"
        return await write(path: "/api/threads/\(ConsoleAddress.component(threadID))/compose", target: threadID, body: .object(["prompt": .string(prompt)]))
    }
    func operation(_ action: String, fields: [String: JSONValue] = [:]) async -> Bool {
        guard let thread = selectedThread else { return false }
        var fields = fields; fields["action"] = .string(action)
        return await write(path: "/api/threads/\(ConsoleAddress.component(thread.id))/operations", target: thread.id, body: .object(fields))
    }
}
