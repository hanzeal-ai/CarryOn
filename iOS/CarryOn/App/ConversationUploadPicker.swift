import SwiftUI
import UniformTypeIdentifiers
import CarryOnCore

struct UploadImportContext {
    let scope: String
    let epoch: UUID
    let key: String
    let target: UploadTarget
    let kind: UploadKind
}

@MainActor @Observable final class UploadPickerState {
    var showing = false
    var context: UploadImportContext?
    func open(_ kind: UploadKind, model: AppModel, key: String, target: UploadTarget) {
        guard model.canUpload, !model.importingUploadKeys.contains(key) else { return }
        context = .init(scope: model.scope, epoch: model.epoch, key: key, target: target, kind: kind)
        showing = true
    }
}

struct ConversationUploadPicker: View {
    @Environment(AppModel.self) private var model
    @Bindable var state: UploadPickerState
    var body: some View {
        Color.clear.frame(width: 0, height: 0)
            .fileImporter(isPresented: $state.showing,
                          allowedContentTypes: state.context?.kind == .directory ? [.folder] : [.data],
                          allowsMultipleSelection: state.context?.kind != .directory) { result in
                guard let context = state.context, context.scope == model.scope, context.epoch == model.epoch else { return }
                switch result {
                case .success(let urls): model.importUploads(urls, context: context)
                case .failure(let error): model.report(error, operation: "选择附件")
                }
            }
    }
}

struct UploadMenuItems: View {
    @Environment(AppModel.self) private var model
    let picker: UploadPickerState
    let key: String
    let target: UploadTarget
    var disabled = false
    var body: some View {
        if model.status["supportsUploads"].bool == true {
            Button { picker.open(.file, model: model, key: key, target: target) } label: {
                Label("上传文件", systemImage: "doc.badge.plus")
            }.disabled(disabled || !model.canUpload || model.importingUploadKeys.contains(key))
            Button { picker.open(.directory, model: model, key: key, target: target) } label: {
                Label("上传文件夹", systemImage: "folder.badge.plus")
            }.disabled(disabled || !model.canUpload || model.importingUploadKeys.contains(key))
        }
    }
}

struct UploadDraftRows: View {
    @Environment(AppModel.self) private var model
    let key: String
    let target: UploadTarget
    var disabled = false
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if model.importingUploadKeys.contains(key) { ProgressView("正在读取附件…").font(.caption) }
            ForEach(model.draftStore.uploads[key] ?? []) { upload in
                HStack(spacing: 8) {
                    Image(systemName: upload.kind == .directory ? "folder" : "doc").frame(width: 24)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(upload.name).font(.subheadline).lineLimit(1)
                        Text(description(upload)).font(.caption).foregroundStyle(upload.failure == nil ? Design.secondary : .red)
                            .lineLimit(2)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    if !upload.complete && !model.uploadingIDs.contains(upload.id) && upload.target == target {
                        Button { model.retryUpload(upload, key: key) } label: {
                            Image(systemName: "arrow.clockwise").frame(width: 44, height: 44)
                        }.disabled(disabled || !model.canUpload).accessibilityLabel("重试上传 \(upload.name)")
                    }
                    Button { model.removeUpload(upload, key: key) } label: {
                        Image(systemName: "xmark").frame(width: 44, height: 44)
                    }.disabled(disabled || model.writing).accessibilityLabel("移除附件 \(upload.name)")
                }.padding(.leading, 10).background(Design.input, in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }
    private func description(_ upload: ConversationUpload) -> String {
        if upload.target != target { return "所属项目已更改，请移除后重新上传" }
        if let failure = upload.failure { return failure }
        if model.uploadingIDs.contains(upload.id) {
            let percent = upload.size > 0 ? min(100, (model.uploadProgress[upload.id] ?? 0) * 100 / upload.size) : 0
            return "正在上传 \(percent)%"
        }
        return upload.complete ? ByteCountFormatter.string(fromByteCount: Int64(upload.size), countStyle: .file) : "等待上传"
    }
}

extension AppModel {
    var canUpload: Bool {
        status["supportsUploads"].bool == true && UploadLimits(value: status["uploadLimits"]) != nil
            && canWrite(.send) && allows(.files)
    }
    func uploadsReady(key: String, target: UploadTarget) -> Bool {
        let uploads = draftStore.uploads[key] ?? []
        return !importingUploadKeys.contains(key) && uploads.count <= ConversationUpload.maximumReferences
            && uploads.allSatisfy { $0.complete && $0.target == target }
    }
    func importUploads(_ urls: [URL], context: UploadImportContext) {
        guard context.scope == scope, context.epoch == epoch, canUpload,
              let limits = UploadLimits(value: status["uploadLimits"]), !urls.isEmpty,
              !importingUploadKeys.contains(context.key) else { return }
        guard urls.count <= ConversationUpload.maximumReferences - (draftStore.uploads[context.key]?.count ?? 0) else {
            report(APIError("每条消息最多上传 \(ConversationUpload.maximumReferences) 个附件")); return
        }
        importingUploadKeys.insert(context.key)
        Task {
            defer { importingUploadKeys.remove(context.key) }
            for url in urls {
                guard context.scope == scope, context.epoch == epoch, canUpload else { return }
                do {
                    let prepared = try await Task.detached(priority: .userInitiated) {
                        guard url.startAccessingSecurityScopedResource() else { throw APIError("无法访问所选附件，请重新选择") }
                        defer { url.stopAccessingSecurityScopedResource() }
                        var coordinationError: NSError?, result: Result<ConversationUpload, Error>?
                        NSFileCoordinator().coordinate(readingItemAt: url, error: &coordinationError) { coordinated in
                            result = Result { try UploadStaging.prepare(url: coordinated, kind: context.kind, target: context.target, limits: limits) }
                        }
                        if let coordinationError { throw coordinationError }
                        guard let result else { throw APIError("无法读取所选附件") }
                        return try result.get()
                    }.value
                    guard context.scope == scope, context.epoch == epoch, canUpload else {
                        Task.detached(priority: .utility) { UploadStaging.remove(prepared) }; return
                    }
                    draftStore.uploads[context.key, default: []].append(prepared); draftStore.save()
                    retryUpload(prepared, key: context.key)
                } catch {
                    if context.scope == scope, context.epoch == epoch { report(error, operation: "读取附件") }
                }
            }
        }
    }
    func retryUpload(_ upload: ConversationUpload, key: String) {
        guard canUpload, !upload.complete, !uploadingIDs.contains(upload.id),
              key.hasPrefix(scope + "\n"), draftStore.uploads[key]?.contains(where: { $0.id == upload.id }) == true,
              let limits = UploadLimits(value: status["uploadLimits"]) else { return }
        let capturedScope = scope, version = epoch
        uploadingIDs.insert(upload.id); uploadProgress[upload.id] = 0
        if let index = draftStore.uploads[key]?.firstIndex(where: { $0.id == upload.id }) { draftStore.uploads[key]?[index].failure = nil }
        uploadTasks[upload.id] = Task {
            defer { uploadingIDs.remove(upload.id); uploadProgress.removeValue(forKey: upload.id); uploadTasks.removeValue(forKey: upload.id) }
            do {
                let identifier = try await UploadTransfer.send(upload, limits: limits, request: { path, body in
                    try Task.checkCancellation()
                    guard self.scope == capturedScope, self.epoch == version, self.canUpload,
                          self.draftStore.uploads[key]?.contains(where: { $0.id == upload.id }) == true else { throw CancellationError() }
                    return try await self.deviceRequest(path, body: body)
                }, progress: { self.uploadProgress[upload.id] = $0 })
                guard scope == capturedScope, epoch == version,
                      let index = draftStore.uploads[key]?.firstIndex(where: { $0.id == upload.id }) else { return }
                draftStore.uploads[key]?[index].uploadID = identifier
                draftStore.uploads[key]?[index].failure = nil; draftStore.save()
            } catch {
                guard scope == capturedScope, epoch == version,
                      let index = draftStore.uploads[key]?.firstIndex(where: { $0.id == upload.id }) else { return }
                draftStore.uploads[key]?[index].failure = error is CancellationError ? "上传已暂停，可重试" : error.localizedDescription
                draftStore.save()
            }
        }
    }
    func removeUpload(_ upload: ConversationUpload, key: String) {
        guard !writing else { return }
        uploadTasks[upload.id]?.cancel()
        draftStore.uploads[key]?.removeAll { $0.id == upload.id }; draftStore.save()
        Task.detached(priority: .utility) { UploadStaging.remove(upload) }
    }
}
