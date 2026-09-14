import Foundation
import Testing
@testable import CarryOnCore

@Test func draftsPersistByCloudDeviceAndConversationAndCorruptionThrows() throws {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: folder) }
    let file = folder.appendingPathComponent("drafts.json")
    #expect(try LocalFiles.read(DraftSnapshot.self, from: file) == nil)
    let texts = ["cloud-a\ndevice-a\nthread": "one", "cloud-b\ndevice-a\nthread": "two", "cloud-a\ndevice-b\nthread": "three"]
    try LocalFiles.write(DraftSnapshot(texts: texts, images: ["cloud-a\ndevice-a\nthread": ["image"]]), to: file)
    let restored = try #require(try LocalFiles.read(DraftSnapshot.self, from: file))
    #expect(restored.texts == texts)
    #expect(restored.images["cloud-a\ndevice-a\nthread"] == ["image"])
    try Data("damaged".utf8).write(to: file)
    #expect(throws: (any Error).self) { try LocalFiles.read(DraftSnapshot.self, from: file) }
    #expect(try String(contentsOf: file, encoding: .utf8) == "damaged")
}

@Test func logsSurviveRestartRedactSecretsAndPreserveCorruptFile() throws {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: folder) }
    let file = folder.appendingPathComponent("logs.json")
    var log = RuntimeLog(storageURL: file)
    log.record(APIError("Bearer session-secret; token=api-secret; login-secret; \"password\":\"json-secret\""), operation: "刷新", workspace: "Mac", blocking: false, secrets: ["login-secret"])
    let restored = RuntimeLog(storageURL: file)
    #expect(restored.entries.count == 1)
    let raw = try String(contentsOf: file, encoding: .utf8)
    for secret in ["session-secret", "api-secret", "login-secret", "json-secret"] { #expect(!raw.contains(secret)) }
    try Data("damaged".utf8).write(to: file)
    var broken = RuntimeLog(storageURL: file)
    #expect(broken.storageFailure != nil)
    broken.record(APIError("later"), operation: "刷新", workspace: "Mac", blocking: false)
    #expect(try String(contentsOf: file, encoding: .utf8) == "damaged")
}

@Test func workspaceSelectionPersistsPerServerAndValidatesMembership() throws {
    let suite = "CarryOn.StorageTests." + UUID().uuidString
    let defaults = try #require(UserDefaults(suiteName: suite))
    defer { defaults.removePersistentDomain(forName: suite) }
    WorkspacePreferences(defaults: defaults).selectDevice("mac-b", server: "cloud-a")
    let restored = WorkspacePreferences(defaults: defaults)
    #expect(restored.selectedDevice(server: "cloud-a", available: ["mac-a", "mac-b"]) == "mac-b")
    #expect(restored.selectedDevice(server: "cloud-b", available: ["mac-a", "mac-b"]) == "mac-a")
    #expect(restored.selectedDevice(server: "cloud-a", available: ["mac-a"]) == "mac-a")
    #expect(restored.selectedDevice(server: "cloud-a", available: []) == "")
}
