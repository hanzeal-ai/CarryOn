import SwiftUI
import CarryOnCore

struct WorkspaceBindingRequests: View {
    @Environment(AppModel.self) private var model
    @State private var requests: [Record] = []
    @State private var failure: String?
    @State private var busy = false
    private let labels = ["view":"查看会话", "create":"新建会话", "send":"发送消息", "stop":"停止任务", "edit":"编辑会话与设置", "files":"查看和下载文件", "approve":"处理审批"]
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("绑定申请").font(.headline)
            if requests.isEmpty { Text("暂无待确认的申请").foregroundStyle(Design.secondary) }
            ForEach(requests) { request in
                VStack(alignment: .leading, spacing: 12) {
                    Text(request.value["name"].text).font(.headline)
                    LabeledContent("当前账号", value: request.value["account"]["username"].text)
                    ForEach(request.value["permissions"].array.compactMap(\.string), id: \.self) { permission in
                        Label(labels[permission] ?? permission, systemImage: "checkmark")
                    }
                    HStack {
                        Button("拒绝", role: .destructive) { Task { await respond(request, reject: true) } }
                        Spacer()
                        Button("确认绑定") { Task { await respond(request, reject: false) } }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent)
                    }.disabled(busy)
                }.padding(18).background(Design.surface, in: RoundedRectangle(cornerRadius: 16))
            }
            if let failure { Text(failure).foregroundStyle(.red) }
        }.task(id: model.addressText) {
            while !Task.isCancelled && model.authenticated {
                await load()
                do { try await Task.sleep(for: .seconds(3)) } catch { return }
            }
        }
    }
    private func load() async {
        let scope = model.addressText, epoch = model.epoch
        do {
            let result = try await model.console("binding/pending")
            guard !Task.isCancelled, scope == model.addressText, epoch == model.epoch else { return }
            requests = try result["requests"].array.map(Record.init); failure = nil
        } catch is CancellationError { return }
        catch {
            if !Task.isCancelled, scope == model.addressText, epoch == model.epoch {
                failure = error.localizedDescription
            }
        }
    }
    private func respond(_ request: Record, reject: Bool) async {
        let epoch = model.epoch
        busy = true; defer { busy = false }
        do {
            let result = try await model.console("binding/respond", body: .object(["id":.string(request.id), "reject":.bool(reject)]))
            guard epoch == model.epoch else { return }
            try await model.refreshDirectory()
            guard epoch == model.epoch else { return }
            if !reject { model.switchDevice(result["deviceId"].text) }
            await load()
        } catch is CancellationError { return }
        catch { if !Task.isCancelled, epoch == model.epoch { failure = error.localizedDescription } }
    }
}
