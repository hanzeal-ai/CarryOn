import Foundation

@main struct DesktopSmoke {
    @MainActor static func main() async throws {
        let model = SettingsModel()
        model.applyLinkStatus(CommandResult(code: 0, text: #"{"state":"expired","error":"连接申请已拒绝","url":"https://example.test"}"#))
        precondition(model.linkIsError && model.linkCanRetry && model.linkDescription == "连接申请已拒绝" && model.linkURL == "https://example.test")
        model.applyLinkStatus(CommandResult(code: 0, text: #"{"state":"pending","verification":"ABC123","expiresIn":299}"#))
        precondition(!model.linkIsError && !model.linkCanRetry)
        model.applyLinkStatus(CommandResult(code: 1, text: "错误：接口不存在"))
        precondition(model.linkIsError && !model.linkCanRetry && model.linkDescription.contains("旧版服务"))
        model.clearService()
        precondition(model.linkDescription.isEmpty && !model.linkIsError)

        await model.refresh()
        precondition(model.running, model.message)
        precondition(model.bindings.count == 2)
        precondition(model.bindings.first(where: {$0.id == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})?.control == false)
        await model.perform(["cloud", "control", "--binding-id", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "--allow-control"])
        precondition(model.bindings.first(where: {$0.id == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})?.control == true, model.message)
        precondition(model.bindings.first(where: {$0.id == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"})?.control == false)
        // An external CLI writes the same service; a desktop refresh must observe it.
        let process = Process()
        process.executableURL = URL(fileURLWithPath: ProcessInfo.processInfo.environment["CARRYON_TEST_EXTERNAL_CLI"]!)
        process.arguments = ["cloud", "control", "--binding-id", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "--read-only", "--state-dir", model.directory]
        let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
        try process.run(); let result = pipe.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
        precondition(process.terminationStatus == 0, String(data: result, encoding: .utf8) ?? "CLI failed")
        await model.refresh()
        precondition(model.bindings.first(where: {$0.id == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})?.control == false)
        let firstDirectory = model.directory
        let secondDirectory = ProcessInfo.processInfo.environment["CARRYON_TEST_SECOND"]!
        guard let second = model.services.first(where: {$0.directory == secondDirectory}),
              let first = model.services.first(where: {$0.directory == firstDirectory}) else { fatalError("Missing workspace") }
        precondition(first.running && second.running && first.port != second.port)
        await model.select(second)
        precondition(model.running && model.directory == secondDirectory)
        await model.perform(["cloud", "control", "--binding-id", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "--allow-control"])
        precondition(model.bindings.first(where: {$0.id == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})?.control == true)
        await model.select(first)
        precondition(model.bindings.first(where: {$0.id == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})?.control == false)
        await model.diagnose()
        precondition(model.diagnostics["codexHome"] as? String == model.codexHome)
        await model.select(second)
        await model.perform(["stop"])
        precondition(!model.running)
        precondition(model.services.first(where: {$0.directory == firstDirectory})?.running == true)
        precondition(model.services.first(where: {$0.directory == secondDirectory})?.running == false)
        let reopened = SettingsModel()
        reopened.directory = secondDirectory
        await reopened.refresh()
        precondition(!reopened.running && reopened.port == String(second.port) && reopened.codexHome == second.codexHome)
        // Desktop-created foreground workspace uses the same catalog and terminates independently.
        let added = await model.add(name: "第三个工作区", path: ProcessInfo.processInfo.environment["CARRYON_TEST_THIRD"]!, port: "0", codex: "")
        precondition(added)
        await model.serve()
        for _ in 0..<20 {
            try await Task.sleep(nanoseconds: 300_000_000)
            await model.refresh()
            if model.running { break }
        }
        precondition(model.running, model.message)
        let thirdDirectory = model.directory
        ForegroundServices.shared.terminateAll()
        for _ in 0..<20 {
            try await Task.sleep(nanoseconds: 300_000_000)
            await model.refresh()
            if !model.running { break }
        }
        precondition(!model.running)
        precondition(ForegroundServices.shared.logs[thirdDirectory]?.contains("已退出") == true)
        precondition(model.services.first(where: {$0.directory == firstDirectory})?.running == true)
        let stoppedRecord = model.services.first { $0.directory == thirdDirectory }!
        await model.remove(stoppedRecord)
        precondition(!model.messageIsError && !model.services.contains { $0.directory == thirdDirectory }, model.message)
        precondition(model.directory != thirdDirectory)
        await model.remove(first)
        precondition(!model.messageIsError && !model.services.contains { $0.directory == firstDirectory }, model.message)
        precondition(FileManager.default.fileExists(atPath: firstDirectory + "/cloud.json"))
        await model.refresh()
        precondition(!model.services.contains { $0.directory == firstDirectory || $0.directory == thirdDirectory })
        print("PASS: remove stopped and running workspaces, preserve files, refresh does not restore removed entries")
        print("PASS: discovery of two services, workspace switch and mutation isolation, doctor, stop isolation, add and foreground lifecycle")
        print("PASS: desktop writes, external CLI reads/writes, desktop refresh observes the same binding; unrelated binding preserved")
    }
}
