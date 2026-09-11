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
    var readSequence = 0
    var historyRevision = 0
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
        epoch = UUID(); updates?.cancel(); directoryUpdates?.cancel()
        let previous = api; api = nil
        Task { await previous?.invalidate() }
        authenticated = false; connected = false; status = .null; history = .null
        devices = []; selectedDevice = ""; selectedThread = nil; selectedProject = nil; activityCount = nil; requests = []; requestHistory = []; requestHistoryError = nil; drafts = [:]; attachments = [:]; credential = ""
    }
    func logout() async {
        guard let api else { return }
        do { _ = try await api.request("logout", method: "POST"); resetSession() }
        catch { report(error) }
    }
    func switchDevice(_ id: String) {
        epoch = UUID(); updates?.cancel(); directoryUpdates?.cancel()
        selectedDevice = id; selectedThread = nil; selectedProject = nil; activityCount = nil; history = .null; status = .null
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
        selectedThread = thread; history = .null; readSequence = 0
        updates?.cancel(); startStream()
    }
    func closeThread() {
        selectedThread = nil; history = .null; readSequence = 0
        updates?.cancel(); startStream()
    }
    func setForeground(_ active: Bool) {
        foreground = active
        updates?.cancel(); directoryUpdates?.cancel(); connected = false
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
    private func startStream() {
        guard !removingDevice, foreground, let client = api, !selectedDevice.isEmpty else { return }
        let generation = epoch, deviceID = selectedDevice, threadID = selectedThread?.id
        updates = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self.epoch == generation, self.selectedThread?.id == threadID else { return }
                var stream: ConsoleStream?
                do {
                    let selection: JSONValue = .object(["threadId": threadID.map(JSONValue.string) ?? .null,
                        "threadIds": .array([]), "subscription": .string(UUID().uuidString)])
                    let connection = try await client.stream(deviceID: deviceID, selection: selection)
                    stream = connection
                    while !Task.isCancelled {
                        let packet = try await connection.next()
                        try Task.checkCancellation()
                        guard self.epoch == generation, self.selectedThread?.id == threadID else { break }
                        self.apply(packet, threadID: threadID)
                    }
                } catch {
                    if !Task.isCancelled && self.epoch == generation && self.selectedThread?.id == threadID {
                        self.connected = false
                        // URLSession can hide a rejected WebSocket handshake behind a transport error.
                        var failure = error
                        if (error as? APIError)?.status != 401 {
                            do { _ = try await client.request("session") }
                            catch { if (error as? APIError)?.status == 401 { failure = error } }
                        }
                        guard !Task.isCancelled, self.epoch == generation else { return }
                        self.report(failure)
                    }
                }
                stream?.close()
                if Task.isCancelled || self.epoch != generation { return }
                do { try await Task.sleep(for: .seconds(2)) } catch { return }
            }
        }
    }
    private func apply(_ packet: JSONValue, threadID: String?) {
        status = packet["status"]; connected = true
        reconcile(packet["jobs"].array)
        if let revision = packet["workspaceRevision"].int, revision != workspaceRevision { workspaceRevision = revision }
        if packet["error"].string != nil { history = .null; error = packet["error"].string; return }
        if let threadID, packet["threadId"].string == threadID, packet["history"].object != nil {
            history = packet["history"]; readSequence = packet["readSequence"].int ?? 0; historyRevision += 1
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
            let result = try await deviceRequest(path, body: body.setting("requestId", .string(id)))
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
        for job in jobs where ["accepted", "completed", "inProgress", "acknowledged"].contains(job["state"].text) {
            try? pending.resolve(scope: scope, target: job["threadId"].text, requestID: job["id"].text)
            try? pending.resolve(scope: scope, target: "new", requestID: job["id"].text)
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
