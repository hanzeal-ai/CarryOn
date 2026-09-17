import SwiftUI
import AppKit

func defaultCodexHome() -> String {
    let path = ProcessInfo.processInfo.environment["CODEX_HOME"].flatMap { $0.isEmpty ? nil : $0 }
        ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex").path
    return NSString(string: path).expandingTildeInPath
}

struct CommandResult: Sendable { let code: Int32; let text: String }
func cliExecutable() -> URL {
    URL(fileURLWithPath: ProcessInfo.processInfo.environment["CARRYON_DESKTOP_CLI"] ?? Bundle.main.executableURL!
        .deletingLastPathComponent().appendingPathComponent("carryon-service").path)
}
func executeCLI(_ arguments: [String], directory: String, input: Data? = nil) -> CommandResult {
    let process = Process(); process.executableURL = cliExecutable()
    process.arguments = arguments + ["--state-dir", directory]
    let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe; process.standardInput = FileHandle.nullDevice
    let inputPipe = input == nil ? nil : Pipe()
    if let inputPipe { process.standardInput = inputPipe }
    do {
        try process.run()
        if let input, let inputPipe {
            try inputPipe.fileHandleForWriting.write(contentsOf: input)
            try inputPipe.fileHandleForWriting.close()
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
        return CommandResult(code: process.terminationStatus, text: String(data: data, encoding: .utf8) ?? "无法读取响应")
    } catch { return CommandResult(code: 1, text: "无法运行 CarryOn CLI：\(error.localizedDescription)") }
}
struct CloudBinding: Identifiable { let id: String; let url: String; let connected: Bool; let control: Bool; let error: String }
struct ServiceRecord: Identifiable, Equatable {
    var id: String { directory }
    let directory: String
    let name: String
    let state: String
    let port: Int
    let codexHome: String
    let backend: String
    var running: Bool { state == "running" }
    var label: String { state == "running" ? "运行中" : state == "unavailable" ? "暂不可用" : "已停止" }
    init(_ value: [String: Any]) {
        directory = value["directory"] as? String ?? ""
        name = value["name"] as? String ?? URL(fileURLWithPath: directory).lastPathComponent
        state = value["state"] as? String ?? "unavailable"
        port = value["port"] as? Int ?? 0
        codexHome = value["codexHome"] as? String ?? defaultCodexHome()
        backend = value["backend"] as? String ?? "desktop-ipc"
    }
}

@MainActor final class ForegroundServices: ObservableObject {
    static let shared = ForegroundServices()
    @Published var logs: [String: String] = [:]
    private var processes: [String: Process] = [:]
    func start(directory: String, port: String, codexHome: String) throws {
        if processes[directory]?.isRunning == true { return }
        let process = Process(); process.executableURL = cliExecutable()
        process.arguments = ["serve", "--state-dir", directory, "--port", port, "--codex-home", codexHome]
        process.standardInput = FileHandle.nullDevice
        let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
        logs[directory] = "正在前台启动…\n"
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { handle.readabilityHandler = nil; return }
            let text = String(decoding: data, as: UTF8.self)
            Task { @MainActor in self?.logs[directory] = String(((self?.logs[directory] ?? "") + text).suffix(64000)) }
        }
        process.terminationHandler = { [weak self] process in
            let code = process.terminationStatus
            Task { @MainActor in
                self?.logs[directory, default: ""] += "\n前台服务已退出（\(code)）"
                if self?.processes[directory] === process { self?.processes[directory] = nil }
            }
        }
        do { try process.run(); processes[directory] = process }
        catch { pipe.fileHandleForReading.readabilityHandler = nil; throw error }
    }
    func terminateAll() { for process in processes.values where process.isRunning { process.terminate() } }
}

@MainActor final class SettingsModel: ObservableObject {
    @Published var directory = ProcessInfo.processInfo.environment["CARRYON_HOME"] ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/CarryOn").path
    @Published var services: [ServiceRecord] = []
    @Published var catalogError = ""
    @Published var running = false
    @Published var enabled = false
    @Published var bridgeRequested = false
    @Published var standby = false
    @Published var standbyDescription = ""
    @Published var bindings: [CloudBinding] = []
    @Published var controller = ""
    @Published var linkDescription = ""
    @Published var linkIsError = false
    @Published var linkCanRetry = false
    @Published var linkURL = ""
    @Published var preferences: [String: Bool] = [:]
    @Published var message = ""
    @Published var messageIsError = false
    @Published var busy = false
    @Published var port = "0"
    @Published var codexHome = defaultCodexHome()
    @Published var processID: Int?
    @Published var diagnostics: [String: Any] = [:]
    @Published var diagnosticText = ""
    private var loadedStartupDirectory: String?
    private var refreshTask: Task<Void, Never>?
    var selectedName: String { services.first(where: {$0.directory == directory})?.name ?? URL(fileURLWithPath: directory).lastPathComponent }

    func call(_ arguments: [String], at path: String? = nil) async -> CommandResult {
        let target = NSString(string: path ?? directory).expandingTildeInPath
        return await Task.detached { executeCLI(arguments, directory: target) }.value
    }
    func object(_ text: String) -> [String: Any]? {
        guard let data = text.data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    func clearService() {
        running = false; enabled = false; bridgeRequested = false; standby = false; bindings = []; processID = nil
        controller = ""; linkDescription = ""; linkIsError = false; linkCanRetry = false; linkURL = ""; preferences = [:]; standbyDescription = ""
    }
    func reload() async {
        let target = directory
        let catalog = await call(["services", "list"], at: target.isEmpty ? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/CarryOn").path : target)
        guard directory == target else { return }
        guard catalog.code == 0, let rows = object(catalog.text)?["services"] as? [[String: Any]] else {
            catalogError = catalog.text; return
        }
        services = rows.map(ServiceRecord.init); catalogError = ""
        if target.isEmpty {
            if let first = services.first {
                directory = first.directory; loadedStartupDirectory = nil
                await reload()
            } else { clearService() }
            return
        }
        if directory == target, !services.contains(where: { $0.directory == target }) {
            directory = services.first?.directory ?? ""; loadedStartupDirectory = nil
            clearService()
            if !directory.isEmpty { await reload() }
            return
        }
        if directory == target, loadedStartupDirectory != target,
           let record = services.first(where: {$0.directory == target}) {
            port = String(record.port); codexHome = record.codexHome; loadedStartupDirectory = target
        }
        let result = await call(["status"], at: target)
        guard directory == target else { return }
        guard let state = object(result.text), let isRunning = state["running"] as? Bool else {
            clearService(); message = result.text; messageIsError = true; return
        }
        guard isRunning else {
            clearService()
            let cloud = await call(["cloud", "status"], at: target)
            guard directory == target else { return }
            applyBindings(cloud)
            return
        }
        let bridge = state["bridge"] as? [String: Any] ?? [:]
        let active = bridge["enabled"] as? Bool ?? false
        let cloud = await call(["cloud", "status"], at: target)
        let power = await call(["standby", "status"], at: target)
        let link = await call(["cloud", "link-status"], at: target)
        let notifications = active ? await call(["notifications", "status"], at: target) : CommandResult(code: 0, text: "{}")
        guard directory == target else { return }
        running = true; enabled = active; bridgeRequested = bridge["requested"] as? Bool ?? active
        if let service = state["service"] as? [String: Any] {
            if let number = service["port"] as? Int { port = String(number) }
            if let path = service["codexHome"] as? String { codexHome = path }
            processID = service["pid"] as? Int
        }
        controller = bridge["controllerId"] as? String ?? ""
        preferences = object(notifications.text)?["preferences"] as? [String: Bool] ?? [:]
        applyBindings(cloud)
        if let powerState = object(power.text) {
            standby = powerState["enabled"] as? Bool ?? false
            standbyDescription = powerState["error"] as? String ?? ((powerState["effective"] as? Bool == true) ? "接电时保持后台运行" : standby ? "等待接电后生效" : "使用系统睡眠设置")
        } else { standby = false; standbyDescription = power.text }
        applyLinkStatus(link)
    }
    func applyBindings(_ result: CommandResult) {
        bindings = (object(result.text)?["bindings"] as? [[String: Any]] ?? []).compactMap { value in
            guard let id = value["id"] as? String, let url = value["url"] as? String else { return nil }
            return CloudBinding(id: id, url: url, connected: value["connected"] as? Bool ?? false,
                                control: value["control"] as? Bool ?? false, error: value["error"] as? String ?? "")
        }
        if result.code != 0 { message = result.text; messageIsError = true }
    }
    func applyLinkStatus(_ result: CommandResult) {
        linkIsError = false; linkCanRetry = false; linkURL = ""
        if let state = object(result.text), let phase = state["state"] as? String {
            linkURL = state["url"] as? String ?? ""
            // Older services may report expired while retaining the terminal rejection.
            if let error = state["error"] as? String, !error.isEmpty {
                linkDescription = error; linkIsError = true; linkCanRetry = true; return
            }
            linkIsError = phase == "expired" || phase == "failed"
            linkCanRetry = linkIsError
            switch phase {
            case "pending": linkDescription = "等待云端确认 · \(state["verification"] as? String ?? "") · 剩余 \(state["expiresIn"] as? Int ?? 0) 秒"
            case "bound": linkDescription = state["bridgeEnabled"] as? Bool == true ? "云端已确认绑定" : "绑定已保存，请打开 Codex 后开启桥接"
            case "expired": linkDescription = "连接申请已过期，请重新申请"
            case "failed": linkDescription = state["error"] as? String ?? "连接申请失败"
            default: linkDescription = ""
            }
        } else {
            linkIsError = true
            linkDescription = result.text.contains("接口不存在")
                ? "此工作区仍运行旧版服务，无法显示申请结果。请停止后重新启动此工作区，再发起申请。"
                : "无法获取连接申请状态，请刷新重试。\n" + result.text
        }
    }
    func refresh() async {
        guard !busy, refreshTask == nil else { return }
        let task = Task { await reload() }; refreshTask = task; await task.value; refreshTask = nil
    }
    func select(_ service: ServiceRecord) async {
        guard !busy else { return }
        loadedStartupDirectory = service.directory
        directory = service.directory; port = String(service.port); codexHome = service.codexHome
        clearService(); message = ""; diagnostics = [:]; diagnosticText = ""
        await refreshTask?.value
        if directory == service.directory { await refresh() }
    }
    func perform(_ arguments: [String]) async {
        guard !busy else { return }
        let target = directory
        busy = true; defer { busy = false }
        await refreshTask?.value
        let result = await call(arguments, at: target)
        messageIsError = result.code != 0
        message = result.code == 0 ? (object(result.text) == nil ? result.text : "操作已完成") : result.text
        await reload()
    }
    func add(name: String, path: String, port: String, codex: String) async -> Bool {
        guard !busy else { return false }
        busy = true; defer { busy = false }; await refreshTask?.value
        var arguments = ["services", "add", "--name", name, "--port", port]
        if !codex.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { arguments += ["--codex-home", codex] }
        let result = await call(arguments, at: path)
        guard result.code == 0, let entry = object(result.text) else { message = result.text; messageIsError = true; return false }
        let record = ServiceRecord(entry)
        diagnostics = [:]; diagnosticText = ""
        loadedStartupDirectory = record.directory
        directory = record.directory; self.port = String(record.port); codexHome = record.codexHome; clearService()
        message = "工作区已保存，请继续设置"; messageIsError = false; await reload(); return true
    }
    func remove(_ service: ServiceRecord) async {
        guard !busy else { return }
        busy = true; defer { busy = false }; await refreshTask?.value
        let status = await call(["status"], at: service.directory)
        guard let active = object(status.text)?["running"] as? Bool else {
            message = status.text; messageIsError = true; return
        }
        if active {
            let stopped = await call(["stop"], at: service.directory)
            guard stopped.code == 0 else { message = stopped.text; messageIsError = true; await reload(); return }
        }
        let result = await call(["services", "remove"], at: service.directory)
        guard result.code == 0 else { message = result.text; messageIsError = true; await reload(); return }
        services.removeAll { $0.directory == service.directory }
        if directory == service.directory {
            directory = services.first?.directory ?? ""
            loadedStartupDirectory = nil
            clearService(); diagnostics = [:]; diagnosticText = ""
        }
        message = ""; messageIsError = false
        await reload()
    }
    func diagnose() async {
        guard !busy else { return }; busy = true; defer { busy = false }; await refreshTask?.value
        let result = await call(["doctor", "--codex-home", codexHome])
        diagnostics = object(result.text) ?? [:]; diagnosticText = result.text
    }
    func serve() async {
        guard !busy else { return }; busy = true; defer { busy = false }; await refreshTask?.value
        do { try ForegroundServices.shared.start(directory: directory, port: port, codexHome: codexHome); message = "前台启动中，请查看运行日志"; messageIsError = false }
        catch { message = error.localizedDescription; messageIsError = true }
    }
}
