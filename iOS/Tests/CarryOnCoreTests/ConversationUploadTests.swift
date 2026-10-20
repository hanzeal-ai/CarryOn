import Foundation
import Darwin
import Testing
@testable import CarryOnCore

private func uploadLimits(chunk: Int = 4, entries: Int = 100, file: Int = 20_971_520, total: Int = 52_428_800) -> UploadLimits {
    UploadLimits(value: .object(["chunkBytes": .number(Double(chunk)), "maxEntries": .number(Double(entries)),
                                "maxFileBytes": .number(Double(file)), "maxTotalBytes": .number(Double(total))]))!
}

private func uploadFixtureRoot() throws -> URL {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    return root
}

@Test func uploadStagingPreservesEmptyDirectoriesAndNormalizesNames() throws {
    let root = try uploadFixtureRoot(); defer { try? FileManager.default.removeItem(at: root) }
    let folder = root.appendingPathComponent("cafe\u{301}", isDirectory: true)
    try FileManager.default.createDirectory(at: folder.appendingPathComponent("empty"), withIntermediateDirectories: true)
    try Data("abc".utf8).write(to: folder.appendingPathComponent("re\u{301}sume.txt"))
    let upload = try UploadStaging.prepare(url: folder, kind: .directory, target: .thread("thread"), limits: uploadLimits())
    defer { UploadStaging.remove(upload) }
    #expect(upload.name.utf8.elementsEqual("café".utf8))
    #expect(upload.entries.map(\.path) == ["café", "café/empty", "café/résume.txt"])
    #expect(upload.entries.map(\.kind) == [.directory, .directory, .file])
    #expect(upload.size == 3)
    let entry = try #require(upload.entries.last)
    #expect(entry.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    #expect(try UploadStaging.chunk(upload, entry: entry, offset: 1, count: 4) == Data("bc".utf8))
    #expect(upload.target == .thread("thread"))
}

@Test func uploadStagingRejectsLinksSpecialFilesAndLimits() throws {
    let root = try uploadFixtureRoot(); defer { try? FileManager.default.removeItem(at: root) }
    let file = root.appendingPathComponent("ordinary")
    try Data("12345".utf8).write(to: file)
    let link = root.appendingPathComponent("link")
    try FileManager.default.createSymbolicLink(at: link, withDestinationURL: file)
    #expect(throws: APIError.self) { try UploadStaging.prepare(url: link, kind: .file, target: .thread("t"), limits: uploadLimits()) }
    #expect(throws: APIError.self) { try UploadStaging.prepare(url: root, kind: .directory, target: .thread("t"), limits: uploadLimits()) }
    try FileManager.default.removeItem(at: link)
    let pipe = root.appendingPathComponent("pipe")
    #expect(mkfifo(pipe.path, 0o600) == 0)
    #expect(throws: APIError.self) { try UploadStaging.prepare(url: root, kind: .directory, target: .thread("t"), limits: uploadLimits()) }
    try FileManager.default.removeItem(at: pipe)
    #expect(throws: APIError.self) { try UploadStaging.prepare(url: file, kind: .file, target: .thread("t"), limits: uploadLimits(file: 4)) }
    #expect(throws: APIError.self) { try UploadStaging.prepare(url: file, kind: .file, target: .thread("t"), limits: uploadLimits(total: 4)) }
    #expect(throws: APIError.self) { try UploadStaging.prepare(url: root, kind: .directory, target: .thread("t"), limits: uploadLimits(entries: 1)) }
}

@Test func uploadTargetsAllowCanonicalCreationReceiptsButRejectDifferentIdentity() {
    let independent = UploadTarget.creation(nil)
    #expect(independent.value.object?["projectId"] == nil)
    #expect(independent.matches(.object(["type": .string("creation"), "projectId": .null])))
    #expect(!independent.matches(.object(["type": .string("creation"), "projectId": .number(3)])))
    #expect(!independent.matches(.object(["type": .string("creation"), "projectId": .string("p")])))
    #expect(UploadTarget.creation("p").matches(.object(["type": .string("creation"), "projectId": .string("p"), "project": .object(["cwd": .string("/native")])])))
    #expect(!UploadTarget.thread("a").matches(UploadTarget.thread("b").value))
    #expect(!independent.matches(UploadTarget.thread("a").value))
}

@Test @MainActor func uploadTransferRetriesSameChunksAndValidatesReceipt() async throws {
    let root = try uploadFixtureRoot(); defer { try? FileManager.default.removeItem(at: root) }
    let file = root.appendingPathComponent("file.txt")
    try Data("abcdefghij".utf8).write(to: file)
    let upload = try UploadStaging.prepare(url: file, kind: .file, target: .creation(nil), limits: uploadLimits())
    defer { UploadStaging.remove(upload) }
    let serverID = String(repeating: "a", count: 32)
    let receipt: JSONValue = .object(["id": .string(serverID), "name": .string(upload.name), "kind": .string("file"),
                                     "target": .object(["type": .string("creation"), "projectId": .null]), "state": .string("uploading")])
    var fail = true, calls: [JSONValue] = [], positions: [Int] = []
    func request(_ path: String, _ body: JSONValue?) async throws -> JSONValue {
        let body = try #require(body); calls.append(body)
        #expect(path == "/api/uploads")
        switch body["action"].text {
        case "begin":
            #expect(body["requestId"].text == upload.id)
            #expect(body["target"] == upload.target.value)
            #expect(body["entries"].array == upload.entries.map(\.value))
            return receipt
        case "chunk":
            let offset = try #require(body["offset"].int)
            let data = try #require(Data(base64Encoded: body["data"].text))
            positions.append(offset)
            if offset == 4 && fail { fail = false; throw APIError("response lost") }
            return .object(["offset": .number(Double(offset + data.count))])
        default: return receipt.setting("state", .string("complete")).setting("path", .string("/not-client-authority"))
        }
    }
    await #expect(throws: APIError.self) { try await UploadTransfer.send(upload, limits: uploadLimits(), request: request) }
    #expect(try await UploadTransfer.send(upload, limits: uploadLimits(), request: request) == serverID)
    #expect(positions == [0, 4, 0, 4, 8])
    #expect(calls.filter { $0["action"].text == "begin" }.count == 2)
    #expect(calls.filter { $0["action"].text == "chunk" && $0["offset"].int == 0 }.first
            == calls.filter { $0["action"].text == "chunk" && $0["offset"].int == 0 }.last)
    await #expect(throws: APIError.self) {
        try await UploadTransfer.send(upload, limits: uploadLimits()) { _, _ in
            receipt.setting("target", UploadTarget.thread("wrong-thread").value)
        }
    }
    await #expect(throws: APIError.self) {
        try await UploadTransfer.send(upload, limits: uploadLimits()) { _, body in
            body?["action"].text == "begin" ? receipt : .object(["offset": .number(10)])
        }
    }
    for malformed in [receipt.setting("state", .string("unknown")), receipt.setting("id", .string("../invalid"))] {
        await #expect(throws: APIError.self) {
            try await UploadTransfer.send(upload, limits: uploadLimits()) { _, _ in malformed }
        }
    }
}

@Test func uploadRequestPermissionsIncludeFilesAndSend() {
    let body: JSONValue = .object(["uploads": .array([.string("id")])])
    #expect(WorkspaceCapability.request(path: "/api/uploads", body: .object(["action": .string("begin")])) == [.send, .files])
    #expect(WorkspaceCapability.request(path: "/api/uploads/id") == [.send, .files])
    #expect(WorkspaceCapability.request(path: "/api/threads/t/compose", body: body) == [.send, .files])
    #expect(WorkspaceCapability.request(path: "/api/threads/t/operations", body: body.setting("action", .string("queue-add"))) == [.send, .files])
    #expect(WorkspaceCapability.request(path: "/api/threads", body: body) == [.create, .send, .files])
    #expect(WorkspaceCapability.request(path: "/api/threads", body: body.setting("settings", .object(["approvalPolicy": .null]))) == [.create, .edit, .send, .files])
}

@Test @MainActor func uploadDraftRecoveryRemainsScopedAndClearsOnlyConfirmedUploads() async throws {
    let root = try uploadFixtureRoot(); defer { try? FileManager.default.removeItem(at: root) }
    let store = DraftStore(file: root.appendingPathComponent("drafts.json")) { _, _ in Issue.record("Unexpected draft error") }
    let scope = "account/device", key = scope + "\nthread"
    let upload = ConversationUpload(name: "file", kind: .file, target: .thread("thread"), entries: [], uploadID: "server-id")
    let later = ConversationUpload(name: "later", kind: .directory, target: .thread("thread"), entries: [], uploadID: "later-id")
    await store.load(scope: scope)
    store.uploads[key] = [upload]
    store.submissions["sent"] = .init(scope: scope, threadID: "thread", draft: .init(uploads: [upload]))
    #expect(await store.flush())
    await store.load(scope: "other"); #expect(store.uploads.isEmpty)
    await store.load(scope: scope); #expect(store.uploads[key] == [upload])
    store.uploads[key]?.append(later)
    let job: JSONValue = .object(["id": .string("sent"), "threadId": .string("thread"), "state": .string("accepted")])
    #expect(!store.reconcileSubmission(scope: "other", job: job))
    #expect(!store.reconcileSubmission(scope: scope, job: job.setting("threadId", .string("wrong"))))
    #expect(store.reconcileSubmission(scope: scope, job: job))
    #expect(store.uploads[key] == [later])
    #expect(ConversationDraft(text: "only text", uploads: [upload]).prompt == "only text")
    let creation = ConversationUpload(name: "folder", kind: .directory, target: .creation(nil), entries: [], uploadID: "creation-id")
    let newKey = scope + "\nnew"
    store.uploads[newKey] = [creation]
    store.texts[newKey] = "original"; store.images[newKey] = ["image"]
    store.submissions["create"] = .init(scope: scope, threadID: "new:", draft: .init(text: "original", images: ["image"], uploads: [creation]), draftKey: newKey, creation: true)
    #expect(await store.flush())
    await store.load(scope: scope)
    let created = job.setting("id", .string("create")).setting("kind", .string("create"))
    #expect(!store.reconcileSubmission(scope: scope, job: created))
    #expect(store.uploads[newKey] == [creation])
    store.texts[newKey] = "later edit"
    #expect(store.reconcileSubmission(scope: scope, job: created.setting("createdThreadId", .string("created-thread"))))
    #expect(store.uploads[newKey]?.isEmpty == true)
    #expect(store.texts[newKey] == "later edit")
    #expect(store.images[newKey]?.isEmpty == true)
    #expect(store.uploads[key] == [later])
}
