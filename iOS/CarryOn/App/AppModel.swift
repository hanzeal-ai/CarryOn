import SwiftUI
import CarryOnCore

@MainActor @Observable final class AppModel {
    var addressText = UserDefaults.standard.string(forKey: "carryon.server") ?? ProductConfiguration.cloudURL
    var username = ""
    var credential = ""
    var authenticated = false
    var busy = false
    var error: String?
    var previewImage: UIImage?
    var runtimeLog = RuntimeLog(storageURL: LocalFiles.directory.appendingPathComponent("runtime-log-v1.json"))
    var devices: [Record] = []
    var selectedDevice = ""
    var status: JSONValue = .null
    var connected = false
    var reconnecting = false
    var selectedThread: Record?
    private(set) var threadParents: [Record] = []
    var selectedProject: Record?
    var activityCount: Int?
    var otherActivityCount = 0
    private var activityRequestVersion = UUID()
    var history: JSONValue = .null
    var sideThreadID: String?
    var sideHistory: JSONValue = .null
    var sideHistoryFailure: String?
    var sideHistoryLimit = 40
    func loadMoreSide() { sideHistoryLimit = min(100000, sideHistoryLimit + 40); updateSelection() }
    func watchSide(_ id: String?) {
        sideThreadID = id; sideHistory = .null; sideHistoryFailure = nil; sideHistoryLimit = 40
        updateSelection()
    }
    var historyFailure: String?
    var historyCache = DisplayHistoryCache()
    var outgoing: [String: JSONValue] = [:]
    var readSequence = 0
    var historyRevision = 0
    var historyLimit = 40
    var readingStates: [String: ConversationReadingState] = [:]
    func readingState(for threadID: String) -> ConversationReadingState {
        let key = scope + "\n" + threadID
        if let state = readingStates[key] { return state }
        if readingStates.count >= 8, let oldest = readingStates.keys.sorted().first { readingStates.removeValue(forKey: oldest) }
        let state = ConversationReadingState(); readingStates[key] = state; return state
    }
    var workspaceRevision = 0
    var requests: [Record] = []
    var drafts: [String: String] = [:] { didSet { scheduleDraftSave() } }
    var attachments: [String: [String]] = [:] { didSet { scheduleDraftSave() } }
    var foreground = true
    var writing = false
    var notice: String?
    private(set) var removingDevice = false
    private let readReceipts = ReadReceiptSync()
    private(set) var epoch = UUID() { didSet { readReceipts.reset(); threadParents = []; previewImage = nil; readingStates = [:] } }
    private var api: ConsoleAPI?
    private var updates: Task<Void, Never>?
    private var liveStream: ConsoleStream?
    private var selectionUpdate: Task<Void, Never>?
    private var directoryVersion = 0
    private var directoryUpdates: Task<Void, Never>?
    private let pending = PendingWrites()
    private let workspacePreferences = WorkspacePreferences()
    private let draftFile = LocalFiles.directory.appendingPathComponent("drafts-v1.json")
    private var draftsLoaded = false
    private var draftSave: Task<Void, Never>?

    private func loadDrafts() {
        draftsLoaded = false
        do {
            let saved = try LocalFiles.read(DraftSnapshot.self, from: draftFile) ?? DraftSnapshot()
            drafts = saved.texts; attachments = saved.images; draftsLoaded = true
        } catch { report(APIError("草稿文件无法读取，原文件已保留；当前编辑暂不能持久保存"), operation: "读取草稿", blocking: false) }
    }
    private func scheduleDraftSave() {
        guard draftsLoaded else { return }
        draftSave?.cancel()
        draftSave = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(250)) } catch { return }
            self?.saveDrafts()
        }
    }
    func saveDrafts() {
        draftSave?.cancel(); draftSave = nil
        guard draftsLoaded else { return }
        do { try LocalFiles.write(DraftSnapshot(texts: drafts, images: attachments), to: draftFile) }
        catch { report(APIError("草稿未能保存到本机，当前内容仍保留在页面中"), operation: "保存草稿", blocking: false) }
    }
    func restoreLogin() async {
        guard !authenticated, !busy, !addressText.isEmpty else { return }
        busy = true
        defer { busy = false }
        let requestedAddress = addressText, version = epoch
        var client: ConsoleAPI?
        do {
            let address = try ConsoleAddress(requestedAddress)
            let restored = ConsoleAPI(address: address, credentials: KeychainSessionCredentials())
            client = restored
            guard try await restored.restoreSession() else { await restored.invalidate(); return }
            let session = try await restored.request("session")
            guard version == epoch, requestedAddress == addressText, !Task.isCancelled else { await restored.invalidate(); return }
            guard case .array(let values) = session["devices"] else { throw APIError("设备目录格式不正确") }
            devices = try values.map(Record.init); api = restored
            addressText = address.base.absoluteString
            loadDrafts(); authenticated = true
            switchDevice(workspacePreferences.selectedDevice(server: addressText, available: devices.map(\.id)))
        } catch {
            await client?.invalidate()
            if version == epoch && requestedAddress == addressText { report(error, operation: "恢复登录", blocking: false) }
        }
    }

    var activityBadgeCount: Int { authenticated ? max(0, activityCount ?? 0) + requests.count : 0 }
    var device: Record? { devices.first { $0.id == selectedDevice } }
    var canWrite: Bool { !removingDevice && authenticated && foreground && connected && status["enabled"].bool == true && status["remoteControl"].bool == true && !writing }
    var conversationReadOnly: Bool { (history["access"]["canInteract"].bool ?? selectedThread?.value["access"]["canInteract"].bool) == false }
    var canInteract: Bool { canWrite && !conversationReadOnly && history["access"]["nativeReady"].bool != false }
    var state: String { connected ? history["status"]["state"].text : "unknown" }
    var scope: String { addressText + "\n" + selectedDevice }
    var connectionLabel: String {
        if device == nil { return "未选择工作区" }
        if device?.value["online"].bool != true { return "离线" }
        if !connected { return reconnecting ? "正在重连" : "连接中" }
        if status["enabled"].bool != true { return "Codex 未就绪" }
        if status["accountAuthenticated"].bool == false { return "Codex 未登录" }
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

    func login(register: Bool = false) async {
        guard !busy else { return }
        busy = true; error = nil
        defer { busy = false }
        var pendingClient: ConsoleAPI?
        do {
            let address = try ConsoleAddress(addressText)
            let client = ConsoleAPI(address: address, credentials: KeychainSessionCredentials())
            pendingClient = client
            _ = try await client.request(register ? "register" : "login", body: .object(["username": .string(username.trimmingCharacters(in: .whitespacesAndNewlines)), "password": .string(credential)]))
            try await finishLogin(client, address: address)
        } catch {
            await abandonLogin(pendingClient)
            report(error, operation: "登录")
        }
    }
    private func finishLogin(_ client: ConsoleAPI, address: ConsoleAddress) async throws {
        let directory = try await client.completeLogin()
        try Task.checkCancellation()
        api = client; devices = directory; credential = ""
        addressText = address.base.absoluteString
        UserDefaults.standard.set(addressText, forKey: "carryon.server")
        loadDrafts(); authenticated = true
        switchDevice(workspacePreferences.selectedDevice(server: addressText, available: devices.map(\.id)))
    }

    func loginWithQRCode(_ code: LoginCode, verification: @escaping (String) -> Void) async throws {
        guard !busy else { throw APIError("正在登录，请稍后重试") }
        busy = true
        defer { busy = false }
        let client = ConsoleAPI(address: code.address, credentials: KeychainSessionCredentials())
        do {
            let claim = UUID().uuidString
            let result = try await client.request("qr/claim", body: .object(["id": .string(code.id), "secret": .string(code.secret), "claim": .string(claim)]))
            guard let number = result["verification"].string else { throw APIError("扫码响应无效") }
            verification(number)
            for _ in 0..<120 {
                try await Task.sleep(for: .milliseconds(1500))
                let state = try await client.request("qr/poll", body: .object(["id": .string(code.id), "claim": .string(claim)]))
                try Task.checkCancellation()
                if state["authenticated"].bool == true {
                    try await finishLogin(client, address: code.address)
                    return
                }
                if state["state"].string == "rejected" { throw APIError("电脑已拒绝本次登录") }
            }
            throw APIError("二维码已过期，请在电脑重新生成")
        } catch {
            await abandonLogin(client)
            throw error
        }
    }

    private func abandonLogin(_ client: ConsoleAPI?) async {
        guard let client else { return }
        do { try await client.cancelLogin() }
        catch {
            runtimeLog.record(error, operation: "撤销未完成登录", workspace: "", blocking: true, secrets: [credential])
            self.error = error.localizedDescription
        }
    }

    func report(_ failure: Error, operation: String = "操作失败", blocking: Bool = true) {
        guard !Task.isCancelled, !(failure is CancellationError) else { return }
        let alert = runtimeLog.record(failure, operation: operation, workspace: device?.title ?? "", blocking: blocking, secrets: [credential])
        if (failure as? APIError)?.status == 401 { resetSession() }
        if alert { error = failure.localizedDescription }
    }
    private func resetSession() {
        saveDrafts(); draftsLoaded = false
        epoch = UUID(); updates?.cancel(); updates = nil; selectionUpdate?.cancel(); liveStream?.close(); liveStream = nil; directoryUpdates?.cancel(); directoryUpdates = nil
        let previous = api; api = nil
        Task { await previous?.invalidate() }
        authenticated = false; connected = false; reconnecting = false; status = .null; history = .null; historyFailure = nil
        devices = []; selectedDevice = ""; selectedThread = nil; sideThreadID = nil; sideHistory = .null; sideHistoryFailure = nil; selectedProject = nil; activityCount = nil; otherActivityCount = 0; requests = []; drafts = [:]; attachments = [:]; historyCache.clear(); outgoing = [:]; credential = ""
    }
    func logout() async {
        guard let api else { return }
        do {
            var body: JSONValue? = nil
            if let installation = UserDefaults.standard.string(forKey: "carryon.push.installation") {
                body = .object(["installationId": .string(installation), "revision": try PushNotifications.nextRevision()])
            }
            // Stop subscriptions before the server invalidates their login session.
            epoch = UUID(); updates?.cancel(); updates = nil; selectionUpdate?.cancel(); liveStream?.close(); liveStream = nil; directoryUpdates?.cancel(); directoryUpdates = nil
            connected = false; reconnecting = false; error = nil; notice = nil
            _ = try await api.request("logout", body: body, method: "POST")
            resetSession()
        }
        catch {
            report(error, operation: "退出登录")
            if authenticated && foreground { startUpdates() }
        }
    }
    func switchDevice(_ id: String) {
        saveDrafts()
        workspacePreferences.selectDevice(id, server: addressText)
        epoch = UUID(); updates?.cancel(); updates = nil; selectionUpdate?.cancel(); liveStream?.close(); liveStream = nil; directoryUpdates?.cancel(); directoryUpdates = nil
        selectedDevice = id; selectedThread = nil; sideThreadID = nil; sideHistory = .null; sideHistoryFailure = nil; selectedProject = nil; activityCount = nil; otherActivityCount = 0; history = .null; historyFailure = nil; status = .null
        connected = false; readSequence = 0; workspaceRevision += 1
        startUpdates()
    }
    func removeDevice(_ id: String) async throws {
        guard !removingDevice, devices.contains(where: { $0.id == id }) else { throw APIError("请先选择工作区") }
        removingDevice = true
        updates?.cancel(); updates = nil; directoryUpdates?.cancel(); directoryUpdates = nil
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
        threadParents = []
        activateThread(thread)
    }
    func enterSubconversation(_ thread: Record, from parentID: String) {
        guard let parent = selectedThread, parent.id == parentID, thread.id != parentID else { return }
        threadParents.append(parent)
        activateThread(thread)
    }
    func returnToParentThread() {
        guard let parent = threadParents.popLast() else { return }
        activateThread(parent)
    }
    private func activateThread(_ thread: Record) {
        sideThreadID = nil; sideHistory = .null; sideHistoryFailure = nil
        historyLimit = readingState(for: thread.id).historyLimit; historyFailure = nil
        otherActivityCount = 0
        selectedThread = thread; history = historyCache.get(scope + "\n" + thread.id) ?? .null; readSequence = 0
        connected = false
        updateSelection()
    }
    func openSubagent(_ id: String, parentID: String) async {
        let capturedScope = scope
        do {
            let result = try await deviceRequest("/api/threads/\(ConsoleAddress.component(parentID))/subagents")
            guard capturedScope == scope, selectedThread?.id == parentID, !Task.isCancelled else { return }
            guard let value = result["threads"].array.first(where: { $0["id"].text == id }) else { throw APIError("此子会话已不可用") }
            enterSubconversation(try Record(value), from: parentID)
        } catch { if capturedScope == scope && selectedThread?.id == parentID { report(error, operation: "打开子会话") } }
    }
    func openLinkedThread(_ id: String, from parentID: String) async {
        let version = epoch
        do {
            let result = try await page("/api/workspace/threads?threadId=" + ConsoleAddress.component(id), key: "threads")
            guard version == epoch, selectedThread?.id == parentID, !Task.isCancelled else { return }
            guard let record = result.records.first(where: { $0.id == id }) else { throw APIError("此会话尚未同步或已不可用，请稍后重试") }
            open(record)
        } catch {
            if version == epoch, selectedThread?.id == parentID { report(error, operation: "打开关联会话") }
        }
    }
    func openNotification(_ target: PushTarget) async {
        guard authenticated, (try? ConsoleAddress(addressText).base.absoluteString) == target.server else { return }
        do {
            try await refreshDirectory()
            guard devices.contains(where: { $0.id == target.deviceID }) else { throw APIError("通知对应的工作区已不可用") }
            if selectedDevice != target.deviceID { switchDevice(target.deviceID) }
            let result = try await page("/api/workspace/threads?threadId=" + ConsoleAddress.component(target.threadID), key: "threads")
            guard let record = result.records.first(where: { $0.id == target.threadID }) else { throw APIError("通知对应的会话已不可用") }
            selectedProject = nil
            open(record)
        } catch { report(error, operation: "打开通知会话") }
    }
    func retryHistory() { historyFailure = nil; updateSelection() }
    func loadEarlierHistory() {
        historyLimit = min(100000, max(historyLimit, history["historyWindow"]["limit"].int ?? 0) + 40)
        updateSelection()
    }
    func closeThread() {
        threadParents = []
        selectedThread = nil; sideThreadID = nil; sideHistory = .null; sideHistoryFailure = nil; history = .null; historyFailure = nil; readSequence = 0
        updateSelection()
    }
    func setForeground(_ active: Bool) {
        guard foreground != active else { return }
        foreground = active
        liveStream?.setForeground(active)
        if !active {
            saveDrafts(); readReceipts.reset()
            directoryUpdates?.cancel(); directoryUpdates = nil
            return
        }
        guard authenticated else { Task { await restoreLogin() }; return }
        startUpdates()
        guard let connection = liveStream else { return }
        let generation = epoch
        // Serialise the resume probe with selection changes on this socket.
        let previous = selectionUpdate
        selectionUpdate = Task { [weak self] in
            await previous?.value
            guard let self, !Task.isCancelled, self.foreground,
                  self.epoch == generation, self.liveStream === connection else { return }
            do {
                try await connection.checkHealth()
                guard !Task.isCancelled, self.foreground, self.epoch == generation,
                      self.liveStream === connection else { return }
                // A fresh subscription reconciles updates missed during suspension.
                if connection.canResubscribe { try await connection.resubscribe(self.selection(self.selectedThread?.id)) }
                else { connection.close() }
            } catch {
                guard !Task.isCancelled, self.epoch == generation, self.liveStream === connection else { return }
                connection.close()
            }
        }
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
        let result = try await console("binding/pending")
        guard version == directoryVersion else { return }
        guard case .array(let values) = result["requests"] else { throw APIError("连接申请格式不正确") }
        requests = try values.map(Record.init)
        try await refreshActivityCounts()
        } catch {
            if version == directoryVersion { throw error }
        }
    }
    func refreshActivityCounts() async throws {
        guard connected, status["enabled"].bool == true, !selectedDevice.isEmpty else { return }
        let version = UUID(), currentThread = selectedThread?.id, capturedScope = scope
        activityRequestVersion = version
        async let allRequest = deviceRequest("/api/activity?limit=1")
        let others: JSONValue?
        if let currentThread {
            others = try await deviceRequest("/api/activity?limit=1&excludeThreadId=" + ConsoleAddress.component(currentThread))
        } else { others = nil }
        let all = try await allRequest
        guard version == activityRequestVersion, capturedScope == scope, currentThread == selectedThread?.id else { return }
        guard let total = all["total"].int, total >= 0,
              let otherTotal = (others ?? all)["total"].int, otherTotal >= 0 else { throw APIError("动态统计格式不正确") }
        activityCount = total
        otherActivityCount = otherTotal
    }

    private func startUpdates() {
        guard !removingDevice, foreground else { return }
        if updates == nil { startStream() }
        guard directoryUpdates == nil else { return }
        directoryUpdates = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                do { try await self.refreshDirectory() }
                catch { if Task.isCancelled { return }; self.report(error, operation: "刷新工作区与动态", blocking: false) }
                do { try await Task.sleep(for: .seconds(5)) } catch { return }
            }
        }
    }
    private func selection(_ threadID: String?) -> JSONValue {
        .object(["threadId": threadID.map(JSONValue.string) ?? .null,
                 "threadIds": .array([]), "historyProtocol": .number(1), "historyLimit": .number(Double(historyLimit)), "subscription": .string(UUID().uuidString),
                 "includeSideChats": .bool(sideThreadID != nil), "sideThreadId": sideThreadID.map(JSONValue.string) ?? .null, "sideHistoryLimit": .number(Double(sideHistoryLimit))])
    }
    private func updateSelection() {
        connected = false
        sideHistory = .null
        guard let connection = liveStream, connection.canResubscribe else {
            updates?.cancel(); updates = nil; liveStream?.close(); liveStream = nil; startStream(); return
        }
        let previous = selectionUpdate, generation = epoch, threadID = selectedThread?.id, limit = historyLimit, sideID = sideThreadID
        selectionUpdate = Task { [weak self] in
            await previous?.value
            guard let self, self.epoch == generation, self.selectedThread?.id == threadID, self.historyLimit == limit,
                  self.liveStream === connection, self.sideThreadID == sideID else { return }
            do { try await connection.resubscribe(self.selection(threadID)) }
            catch {
                guard !Task.isCancelled, self.epoch == generation, self.liveStream === connection else { return }
                connection.close(); self.reportStreamFailure(error)
            }
        }
    }
    private func startStream() {
        guard !removingDevice, foreground, let client = api, !selectedDevice.isEmpty else { return }
        updates?.cancel()
        let generation = epoch, deviceID = selectedDevice
        updates = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self.epoch == generation else { return }
                if !self.foreground {
                    do { try await Task.sleep(for: .seconds(1)) } catch { return }
                    continue
                }
                var stream: ConsoleStream?
                do {
                    let connection = try await client.stream(deviceID: deviceID, selection: self.selection(self.selectedThread?.id))
                    stream = connection
                    try Task.checkCancellation()
                    self.liveStream = connection
                    connection.setForeground(self.foreground)
                    while !Task.isCancelled {
                        let packet = try await connection.next()
                        try Task.checkCancellation()
                        guard self.epoch == generation else { break }
                        guard packet["threadId"].string == self.selectedThread?.id else { continue }
                        await self.apply(packet, threadID: self.selectedThread?.id)
                    }
                } catch {
                    if !Task.isCancelled && self.epoch == generation {
                        self.connected = false
                        var failure = error
                        if self.foreground && (error as? APIError)?.status != 401 {
                            do { _ = try await client.request("session") }
                            catch { if (error as? APIError)?.status == 401 { failure = error } }
                        }
                        guard !Task.isCancelled, self.epoch == generation else { stream?.close(); return }
                        self.reportStreamFailure(failure)
                    }
                }
                stream?.close()
                if self.liveStream === stream { self.liveStream = nil }
                if Task.isCancelled || self.epoch != generation { return }
                do { try await Task.sleep(for: .seconds(2)) } catch { return }
            }
        }
    }
    private func apply(_ packet: JSONValue, threadID: String?) async {
        let generation = epoch, capturedScope = scope, limit = historyLimit
        let incoming = packet["history"]
        let changed = incoming["historyRevision"].string.map { $0 != history["historyRevision"].string } ?? (incoming != history)
        var encodedBytes = -1
        if changed, incoming.object != nil, packet["threadId"].string == threadID {
            encodedBytes = await Task.detached(priority: .userInitiated) {
                (try? incoming.encoded().count) ?? -1
            }.value
        }
        // Selection and logout can change while measuring a large snapshot.
        guard !Task.isCancelled, epoch == generation, scope == capturedScope,
              selectedThread?.id == threadID, historyLimit == limit else { return }
        status = packet["status"]; connected = true; reconnecting = false
        if let sideThreadID, packet["sideThreadId"].string == sideThreadID {
            sideHistoryFailure = packet["sideError"].string
            if sideHistoryFailure != nil { sideHistory = .null }
            else if packet["sideHistory"].object != nil { sideHistory = packet["sideHistory"] }
        }
        reconcile(packet["jobs"].array)
        reconcileOutgoing()
        if let revision = packet["workspaceRevision"].int, revision != workspaceRevision { workspaceRevision = revision }
        if packet["error"].string != nil { historyFailure = packet["error"].string; return }
        historyFailure = nil
        if let threadID, packet["threadId"].string == threadID, packet["history"].object != nil {
            let sequence = packet["readSequence"].int ?? 0
            if changed { history = incoming; historyCache.set(scope + "\n" + threadID, history, encodedBytes: encodedBytes) }
            reconcileOutgoing()
            if changed || sequence != readSequence { historyRevision += 1 }
            readSequence = sequence
        }
    }
    func markDisplayed(threadID: String, sequence: Int) async {
        guard foreground, selectedThread?.id == threadID, connected, sequence > 0 else { return }
        let version = epoch
        readReceipts.enqueue(threadID: threadID, sequence: sequence, send: { [weak self] thread, cursor in
            guard let self, self.epoch == version, self.foreground, self.authenticated else { throw CancellationError() }
            _ = try await self.deviceRequest("/api/notifications/read", body: .object(["threadId": .string(thread), "sequence": .number(Double(cursor))]))
        }, failure: { [weak self] failure, persistent in
            guard let self, self.epoch == version else { return }
            if persistent {
                self.report(APIError("已读状态暂未同步，将自动重试（" + failure.localizedDescription + "）"), operation: "同步已读状态", blocking: false)
            } else { self.report(failure, operation: "同步已读状态", blocking: false) }
        })
    }
    @discardableResult func write(path: String, target: String, body: JSONValue, awaitCompletion: Bool = false) async -> Bool {
        guard canWrite else { error = "当前连接不可写，请检查本机授权与连接状态"; return false }
        if target == selectedThread?.id && !canInteract { error = conversationReadOnly ? "此子会话为只读" : "会话尚未就绪"; return false }
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
            var result: JSONValue
            do { result = try await deviceRequest(path, body: body.setting("requestId", .string(id))) }
            catch {
                if composing, version == epoch, let item = outgoing[id] { outgoing[id] = OutgoingMessageProjection.merge(item, .object(["state": .string("uncertain")])) }
                throw error
            }
            if awaitCompletion {
                let deadline = Date().addingTimeInterval(20)
                while ["preparing", "dispatching"].contains(result["state"].text) {
                    guard version == epoch, capturedScope == scope else { return false }
                    guard Date() < deadline else { throw APIError("操作仍在处理，尚未确认结果；原请求已保留，请稍后核对") }
                    try await Task.sleep(for: .milliseconds(300))
                    guard version == epoch, capturedScope == scope else { return false }
                    result = try await deviceRequest("/api/jobs/" + ConsoleAddress.component(id))
                }
                guard version == epoch, capturedScope == scope else { return false }
                guard result["state"].text == "completed" || ((composing || (path == "/api/threads" && result["createdThreadId"].string != nil)) && ["accepted", "inProgress"].contains(result["state"].text)) else {
                    try pending.reconcile(scope: capturedScope, job: result.setting("id", .string(id)).setting("threadId", .string(target)))
                    throw APIError(result["error"].string ?? "操作结果尚未确认，请核对请求记录")
                }
            }
            if composing, version == epoch { mergeOutgoing(result.setting("id", .string(id))); reconcileOutgoing() }
            guard version == epoch else { return false }
            try pending.reconcile(scope: capturedScope, job: result.setting("id", .string(id)).setting("threadId", .string(target)))
            let state = result["state"].text
            if ["failed", "interrupted"].contains(state) {
                throw APIError(result["error"].string ?? (state == "interrupted" ? "操作已暂停" : "操作失败"))
            }
            guard ["preparing", "dispatching", "completed", "accepted", "inProgress"].contains(state) else {
                throw APIError((result["error"].string ?? "操作结果尚未确认") + "；请在请求记录与 Codex App 核对，原请求编号已保留。")
            }
            if ["accepted", "completed", "inProgress"].contains(state) { try pending.accepted(scope: capturedScope, target: target) }
            return true
        } catch { if version == epoch { report(error, operation: path.hasSuffix("/compose") ? "发送消息" : "提交操作") }; return false }
    }
    func reconcile(_ jobs: [JSONValue]) {
        for job in jobs { mergeOutgoing(job, live: true) }
        for job in jobs { try? pending.reconcile(scope: scope, job: job) }
    }
    var visibleOutgoing: [JSONValue] {
        outgoingFor(selectedThread?.id)
    }
    func outgoingFor(_ threadID: String?) -> [JSONValue] {
        outgoing.values.filter { $0["scope"].text == scope && $0["threadId"].text == threadID }.sorted { ($0["created"].int ?? 0, $0["id"].text) < ($1["created"].int ?? 0, $1["id"].text) }
    }
    private func mergeOutgoing(_ job: JSONValue, live: Bool = false) {
        let id = job["id"].text
        guard let previous = outgoing[id], previous["scope"].text == scope else { return }
        outgoing[id] = OutgoingMessageProjection.merge(previous, job, live: live)
    }
    private func reconcileOutgoing() {
        for snapshot in [history, sideHistory] {
            for item in outgoingFor(snapshot["thread"]["id"].string) {
                if OutgoingMessageProjection.isReflected(item, in: snapshot) { outgoing.removeValue(forKey: item["id"].text) }
            }
        }
    }
    private func reportStreamFailure(_ failure: Error) {
        connected = false; reconnecting = true
        report(failure, operation: "实时连接", blocking: false)
    }
    func confirmJob(_ job: JSONValue) async {
        do {
            if job["state"].text == "uncertain" {
                _ = try await deviceRequest("/api/jobs/\(ConsoleAddress.component(job["id"].text))/acknowledge", body: .object(["confirmed": .bool(true)]))
            }
            try pending.resolve(scope: scope, target: job["threadId"].text, requestID: job["id"].text)
            try pending.resolve(scope: scope, target: "new", requestID: job["id"].text)
            if let project = job["creationProject"]["groupId"].string {
                try pending.resolve(scope: scope, target: "new:" + project, requestID: job["id"].text)
            }
        } catch { report(error, operation: "核对请求结果") }
    }
    var editContext: JSONValue = .null
    var editingMessage: JSONValue {
        editContext["scope"].text == scope && editContext["threadId"].text == selectedThread?.id ? editContext["item"] : .null
    }
    func beginEditing(_ item: JSONValue) {
        guard let thread = selectedThread, canWrite, state == "idle", item["turnId"] == history["controls"]["lastTurnId"] else { return }
        if editingMessage == .null {
            editContext = .object(["scope": .string(scope), "threadId": .string(thread.id),
                "draft": .string(draft), "images": .array(draftImages.map(JSONValue.string)), "item": item])
        }
        draft = history["controls"]["lastUserText"].text
        draftImages = []
    }
    func cancelEditing() {
        guard editingMessage != .null else { return }
        draft = editContext["draft"].text; draftImages = editContext["images"].array.compactMap(\.string)
        editContext = .null
    }
    func compose(images: [JSONValue] = [], queued: Bool = false) async -> Bool {
        guard let thread = selectedThread else { return false }
        let text = draft
        let capturedKey = scope + "\n" + thread.id
        let sent = ConversationDraft(text: text, images: images.compactMap(\.string))
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !images.isEmpty else { return false }
        var body: JSONValue = .object(["prompt": .string(text)])
        if !images.isEmpty { body = body.setting("images", .array(images)) }
        let edit = editingMessage
        let success: Bool
        if edit != .null {
            success = await operation("edit", fields: ["turnId": edit["turnId"], "prompt": .string(text), "confirmed": .bool(true)])
        } else if queued {
            success = await perform("queue-add", target: .init(scope: scope, threadID: thread.id), fields: ["prompt": .string(text), "images": .array(images), "queueFingerprint": history["queue"]["fingerprint"]])
        } else {
            success = await write(path: "/api/threads/\(ConsoleAddress.component(thread.id))/compose", target: thread.id, body: body)
        }
        if success, edit != .null {
            if editingMessage == edit { cancelEditing() }
            return true
        }
        if success {
            var current = ConversationDraft(text: drafts[capturedKey] ?? "", images: attachments[capturedKey] ?? [])
            current.didSubmit(sent)
            drafts[capturedKey] = current.text; attachments[capturedKey] = current.images
            saveDrafts()
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
        return await perform(action, target: .init(scope: scope, threadID: thread.id), fields: fields)
    }
}
