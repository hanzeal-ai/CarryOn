import SwiftUI
import VisionKit
import AVFoundation
import CarryOnCore

struct WorkspaceBindingView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var camera = false
    @State private var code: WorkspaceBindingCode?
    @State private var details: JSONValue = .null
    @State private var failure: String?
    @State private var busy = false
    @State private var waiting = false
    private let labels = ["view":"查看会话", "create":"新建会话", "send":"发送消息", "stop":"停止任务", "edit":"编辑会话与设置", "files":"查看和下载文件", "approve":"处理审批"]
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if camera {
                        QRScanner(onScan: { raw in
                            camera = false
                            Task { await inspect(raw) }
                        }, onFailure: { failure = "相机暂不可用"; camera = false })
                            .frame(height: 320).clipShape(RoundedRectangle(cornerRadius: 16))
                        Text("扫描电脑上 carryon init 或桌面端显示的工作区二维码。").font(.callout).foregroundStyle(Design.secondary)
                    }
                    if details.object != nil {
                        Image(systemName: "laptopcomputer").font(.system(size: 36)).foregroundStyle(Design.ink)
                        Text(details["name"].text).font(.title2.weight(.semibold))
                        LabeledContent("当前账号", value: details["account"]["username"].text)
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(details["permissions"].array.compactMap(\.string), id: \.self) { permission in
                                Label(labels[permission] ?? permission, systemImage: "checkmark")
                            }
                        }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(.white, in: RoundedRectangle(cornerRadius: 16))
                        Button { Task { await accept() } } label: {
                            Text(waiting ? "等待电脑确认" : "确认绑定").fontWeight(.semibold).frame(maxWidth: .infinity, minHeight: 50)
                        }.foregroundStyle(.white).background(Design.ink, in: RoundedRectangle(cornerRadius: 13)).disabled(busy || waiting)
                    }
                    if busy { ProgressView() }
                    if let failure {
                        Text(failure).foregroundStyle(.red)
                        Button("重新扫码") { Task { await enableCamera() } }.disabled(busy)
                    }
                }.padding(24)
            }.background(Design.background).navigationTitle("绑定工作区").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .task { await enableCamera() }
                .task(id: waiting) {
                    guard waiting, let code else { return }
                    do {
                        while !Task.isCancelled {
                            try await Task.sleep(for: .seconds(1.5))
                            let state = try await model.console("binding/inspect", body: code.body)
                            if state["state"].text == "bound" { try await model.refreshDirectory(); dismiss(); return }
                        }
                    } catch { if !Task.isCancelled { failure = error.localizedDescription; waiting = false } }
                }
        }
    }
    private func enableCamera() async {
        failure = nil; details = .null; code = nil
        guard DataScannerViewController.isSupported, await AVCaptureDevice.requestAccess(for: .video), DataScannerViewController.isAvailable else {
            failure = "相机不可用，请在系统设置中允许 CarryOn 使用相机。"; return
        }
        camera = true
    }
    private func inspect(_ raw: String) async {
        busy = true; defer { busy = false }
        do {
            let parsed = try WorkspaceBindingCode(raw)
            guard parsed.address == (try ConsoleAddress(model.addressText)) else { throw APIError("二维码属于其他云端，请先登录对应云端账号") }
            details = try await model.console("binding/inspect", body: parsed.body)
            code = parsed
        } catch { failure = error.localizedDescription }
    }
    private func accept() async {
        guard let code else { return }
        busy = true; defer { busy = false }
        do {
            let result = try await model.console("binding/accept", body: code.body)
            if result["state"].text == "accepted" { waiting = true; return }
            try await model.refreshDirectory()
            model.switchDevice(result["deviceId"].text)
            dismiss()
        } catch { failure = error.localizedDescription }
    }
}
