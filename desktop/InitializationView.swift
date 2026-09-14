import SwiftUI
import CoreImage.CIFilterBuiltins

@MainActor struct InitializationView: View {
    @ObservedObject var model: SettingsModel
    @Environment(\.dismiss) private var dismiss
    @State private var url = ""
    @State private var autoStart = true
    @State private var qr: NSImage?
    @State private var phase = "new"
    @State private var message = ""
    @State private var busy = false
    @State private var polling: Task<Void, Never>?
    @State private var accounts: [[String: Any]] = []
    @State private var selectedAccount = ""
    @State private var fineGrained = false
    @State private var permissions: Set<String> = ["view", "files"]
    @State private var codexAvailable = false
    private var allowsControl: Bool { !permissions.subtracting(["view", "files"]).isEmpty }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("连接工作区").font(.title2.weight(.semibold))
            Label("本机 Codex App", systemImage: "laptopcomputer").foregroundStyle(DesktopDesign.secondary)
            if !codexAvailable { Text("尚未发现运行中的 Codex App，可以先绑定，服务启动后将等待连接。").font(.caption).foregroundStyle(DesktopDesign.secondary) }
            if phase != "waiting" && phase != "bound" {
                TextField("云端 HTTPS 地址", text: $url).textFieldStyle(.roundedBorder)
                    .onChange(of: url) { _ in accounts = []; selectedAccount = "" }
                Button("从已确认账号选择") { Task {
                    if let state = await exchange(["action":"known-accounts", "url":url]) {
                        accounts = state["accounts"] as? [[String:Any]] ?? []
                        let warnings = state["warnings"] as? [String] ?? []
                        message = warnings.isEmpty ? (accounts.isEmpty ? "此云端暂无已确认账号，请扫码绑定。" : "") : warnings.joined(separator: "\n")
                    }
                } }.disabled(busy || url.isEmpty)
                if !accounts.isEmpty {
                    Picker("使用者", selection: $selectedAccount) {
                        Text("其他账号扫码绑定").tag("")
                        ForEach(accounts.indices, id: \.self) { index in Text(accounts[index]["username"] as? String ?? "").tag(accounts[index]["id"] as? String ?? "") }
                    }
                }
                Toggle("绑定完成后自动启动服务", isOn: $autoStart)
                Toggle("允许手机操作会话", isOn: Binding(get: {allowsControl}, set: {value in permissions = Set(value ? ["view","create","send","stop","edit","files","approve"] : ["view","files"]) }))
                DisclosureGroup("细分权限", isExpanded: $fineGrained) {
                    ForEach([("create","新建会话"),("send","发送消息"),("stop","停止任务"),("edit","编辑会话与设置"),("files","查看和下载文件"),("approve","处理审批")], id: \.0) { key, label in
                        Toggle(label, isOn: Binding(get: {permissions.contains(key)}, set: { value in if value {permissions.insert(key)} else {permissions.remove(key)} }))
                    }
                }
            }
            if let qr {
                Image(nsImage: qr).interpolation(.none).resizable().scaledToFit().frame(width: 250, height: 250)
                    .padding(16).background(.white).frame(maxWidth: .infinity)
                Text("在 CarryOn App 登录账号后扫码，核对工作区及权限并确认。").font(.callout)
            }
            if !message.isEmpty { Text(message).font(.callout).foregroundStyle(DesktopDesign.secondary).textSelection(.enabled) }
            HStack {
                if busy { ProgressView().controlSize(.small) }
                Spacer()
                Button(phase == "bound" ? "完成" : "稍后继续") { dismiss() }.keyboardShortcut(.cancelAction)
                if phase != "waiting" && phase != "bound" {
                    Button(selectedAccount.isEmpty ? "生成二维码" : "确认分配") { Task { await prepare() } }.buttonStyle(AccentButton()).disabled(busy || url.isEmpty)
                }
            }
        }.padding(28).frame(width: 470).background(DesktopDesign.background)
            .task {
                if let state = await exchange(["action":"status"]) {
                    url = state["url"] as? String ?? ""
                    autoStart = state["autoStart"] as? Bool ?? true
                    permissions = Set(state["permissions"] as? [String] ?? ["view","files"])
                    render(state)
                    if phase == "waiting" { beginPolling() }
                }
            }.onDisappear { polling?.cancel() }
    }
    private func exchange(_ fields: [String: Any]) async -> [String: Any]? {
        guard let data = try? JSONSerialization.data(withJSONObject: fields) else { return nil }
        let target = model.directory
        let result = await Task.detached { executeCLI(["init", "--input-json"], directory: target, input: data) }.value
        guard !Task.isCancelled else { return nil }
        guard result.code == 0, let state = model.object(result.text) else { message = result.text; return nil }
        return state
    }
    private func prepare() async {
        busy = true; defer { busy = false }
        var fields: [String: Any] = ["action":"prepare", "url":url, "autoStart":autoStart, "control":allowsControl,
                                     "codexHome":model.codexHome, "port":Int(model.port) ?? 0]
        fields["permissions"] = permissions.sorted()
        if let account = accounts.first(where: { $0["id"] as? String == selectedAccount }) {
            fields["accountId"] = selectedAccount; fields["sourceDirectory"] = account["sourceDirectory"]; fields["sourceBindingId"] = account["sourceBindingId"]
        }
        if let state = await exchange(fields) {
            render(state)
            if phase == "waiting" { beginPolling() }
        }
    }
    private func render(_ state: [String: Any]) {
        codexAvailable = (state["environment"] as? [String: Any])?["ipcAvailable"] as? Bool ?? false
        phase = state["state"] as? String ?? "new"
        if let link = state["qrURL"] as? String {
            let filter = CIFilter.qrCodeGenerator(); filter.message = Data(link.utf8)
            if let image = filter.outputImage, let cg = CIContext().createCGImage(image, from: image.extent) {
                qr = NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
            } else { message = "无法显示二维码，请使用 CLI 初始化。" }
        }
        if phase == "bound" {
            qr = nil
            message = state["bridgeConnected"] as? Bool == true && state["cloudConnected"] as? Bool == true ? "工作区已就绪，可在手机使用。" : state["running"] as? Bool == true ? "绑定已完成，正在等待 Codex 或云端连接。" : "绑定已保存，点击工作区的启动服务即可运行。"
        }
    }
    private func beginPolling() {
        polling?.cancel()
        polling = Task {
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
                guard let state = await exchange(["action":"poll"]) else { phase = "configured"; qr = nil; return }
                render(state)
                if phase == "bound" { await model.refresh(); return }
            }
        }
    }
}
