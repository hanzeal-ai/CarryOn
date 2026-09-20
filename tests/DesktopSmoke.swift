import Foundation

@main struct DesktopSmoke {
    @MainActor static func main() async throws {
        let model = SettingsModel()
        let firstCreated = await model.createWorkspace(name: "独立工作区 A")
        precondition(firstCreated, model.message)
        let firstDirectory = model.directory, firstHome = model.codexHome
        await model.perform(["start"])
        precondition(model.running && model.enabled, model.message)
        let auth = await model.call(["services", "auth-status"])
        precondition(auth.code == 0 && model.object(auth.text)?["requiresOpenaiAuth"] as? Bool == true)
        let secondCreated = await model.createWorkspace(name: "独立工作区 B")
        precondition(secondCreated, model.message)
        precondition(model.directory != firstDirectory && model.codexHome != firstHome)
        await model.perform(["start"])
        precondition(model.running && model.enabled, model.message)
        let secondDirectory = model.directory
        let marker = URL(fileURLWithPath: firstHome).appendingPathComponent("keep-session-fixture")
        try Data("keep".utf8).write(to: marker)
        await model.refresh()
        let first = model.services.first { $0.directory == firstDirectory }!
        await model.remove(first)
        precondition(!model.messageIsError, model.message)
        precondition(FileManager.default.fileExists(atPath: marker.path))
        precondition(!model.services.contains { $0.directory == firstDirectory })
        precondition(model.services.first { $0.directory == secondDirectory }?.running == true)
        let second = model.services.first { $0.directory == secondDirectory }!
        await model.remove(second)
        await model.refresh()
        precondition(!model.services.contains { $0.directory == firstDirectory || $0.directory == secondDirectory })
        print("PASS: name-only creation, isolated app-server homes, independent process startup, model account separation, deletion stops only selected service and retains files")
    }
}
