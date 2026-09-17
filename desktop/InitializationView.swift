import SwiftUI
import CoreImage.CIFilterBuiltins

@MainActor struct InitializationView: View {
    @ObservedObject var model: SettingsModel
    var bindingID: String? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var url = ""
    @State private var autoStart = true
    @State private var qr: NSImage?
    @State private var phase = "new"
    @State private var message = ""
    @State private var busy = false
    @State private var applyingConfirmed = false
    @State private var confirmedAccount = ""
    @State private var polling: Task<Void, Never>?
    @State private var accounts: [[String: Any]] = []
    @State private var selectedAccount = ""
    @State private var fineGrained = false
    @State private var permissions: Set<String> = ["view", "files"]
    @State private var codexAvailable = false
    @State private var independentCodex = false
    private var allowsControl: Bool { !permissions.subtracting(["view", "files"]).isEmpty }
    private var cloudURL: String { url.trimmingCharacters(in: .whitespacesAndNewlines) }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("连接工作区").font(.title2.weight(.semibold))
            Label(independentCodex ? "独立 Codex 工作区" : "本机 Codex App", systemImage: "laptopcomputer").foregroundStyle(DesktopDesign.secondary)
            if !independentCodex && !codexAvailable { Text("尚未发现运行中的 Codex App，可以先绑定，服务启动后将等待连接。").font(.caption).foregroundStyle(DesktopDesign.secondary) }
            if phase != "waiting" && phase != "bound" && phase != "confirming" {
                Button("从已确认账号选择") { Task {
                    if let state = await exchange(["action":"known-accounts", "url":cloudURL]) {
                        accounts = state["accounts"] as? [[String:Any]] ?? []
                        let warnings = state["warnings"] as? [String] ?? []
                        message = warnings.isEmpty ? (accounts.isEmpty ? "此云端暂无已确认账号，请扫码绑定。" : "") : warnings.joined(separator: "\n")
                    }
                } }.disabled(busy || cloudURL.isEmpty)
                if !accounts.isEmpty {
                    Picker("使用者", selection: $selectedAccount) {
                        Text("其他账号扫码绑定").tag("")
                        ForEach(accounts.indices, id: \.self) { index in Text(accounts[index]["username"] as? String ?? "").tag(accounts[index]["id"] as? String ?? "") }
                    }
                }
                Toggle("绑定完成后自动启动服务", isOn: $autoStart)
                Toggle("允许手机操作会话", isOn: Binding(get: {allowsControl}, set: {value in permissions = Set(value ? ["view","create","send","stop","edit","files","approve"] : ["view","files"]) }))
                DisclosureGroup("细分权限", isExpanded: $fineGrained) {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach([("create","新建会话"),("send","发送消息"),("stop","停止任务"),("edit","编辑会话与设置"),("files","查看和下载文件"),("approve","处理审批")], id: \.0) { key, label in
                            Toggle(label, isOn: Binding(get: {permissions.contains(key)}, set: { value in if value {permissions.insert(key)} else {permissions.remove(key)} }))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
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
                if phase == "waiting" {
                    Button("取消") { Task { await cancelBinding() } }.disabled(busy)
                }
                Spacer()
                Button(phase == "bound" ? "完成" : "稍后继续") { dismiss() }.keyboardShortcut(.cancelAction)
                if phase == "confirming" {
                    Button("重试") { Task {
                        busy = true; defer { busy = false }
                        if let state = await exchange(["action":"poll"]) { render(state) }
                    } }.disabled(busy)
                    Button("应用扫码结果") { applyingConfirmed = true }.disabled(busy)
                } else if phase == "unverified" {
                    Button("重试") { Task { await load() } }.disabled(busy)
                } else if phase != "waiting" && phase != "bound" {
                    Button(selectedAccount.isEmpty ? "生成二维码" : "确认分配") { Task { await prepare() } }.buttonStyle(AccentButton()).disabled(busy || cloudURL.isEmpty)
                }
            }
        }.padding(28).frame(width: 470).background(DesktopDesign.background)
            .task { await load() }.onDisappear { polling?.cancel() }
            .alert("应用本次扫码绑定？", isPresented: $applyingConfirmed) {
                Button("取消", role: .cancel) {}
                Button("应用") { Task {
                    busy = true; defer { busy = false }
                    if let state = await exchange(["action":"apply-confirmed"]) { render(state) }
                } }
            } message: { Text("将使用本次扫码确认的账号「\(confirmedAccount)」替换此云端当前的绑定。") }
    }
    private func load() async {
        busy = true; defer { busy = false }
        if let state = await exchange(["action":"status", "useDefaultCloud":bindingID == nil]) {
            let savedURL = (state["url"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            url = savedURL
            autoStart = state["autoStart"] as? Bool ?? true
            permissions = Set(state["permissions"] as? [String] ?? ["view","files"])
            render(state)
            if phase == "waiting" { beginPolling() }
        }
    }
    private func exchange(_ fields: [String: Any]) async -> [String: Any]? {
        var fields = fields
        if let bindingID { fields["bindingId"] = bindingID }
        guard let data = try? JSONSerialization.data(withJSONObject: fields) else { return nil }
        let target = model.directory
        let result = await Task.detached { executeCLI(["init", "--input-json"], directory: target, input: data) }.value
        guard !Task.isCancelled, model.directory == target else { return nil }
        guard result.code == 0, let state = model.object(result.text) else { message = result.text; return nil }
        return state
    }
    private func prepare() async {
        busy = true; defer { busy = false }
        var fields: [String: Any] = ["action":"prepare", "url":cloudURL, "autoStart":autoStart, "control":allowsControl,
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
        independentCodex = (state["environment"] as? [String: Any])?["backend"] as? String == "app-server"
        codexAvailable = (state["environment"] as? [String: Any])?["ipcAvailable"] as? Bool ?? false
        phase = state["state"] as? String ?? "new"
        message = state["error"] as? String ?? ""
        confirmedAccount = (state["confirmedAccount"] as? [String: Any])?["username"] as? String ?? ""
        qr = nil
        if let link = state["qrURL"] as? String {
            let filter = CIFilter.qrCodeGenerator(); filter.message = Data(link.utf8)
            if let image = filter.outputImage, let cg = CIContext().createCGImage(image, from: image.extent) {
                qr = NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
            } else { message = "无法显示二维码，请使用 CLI 初始化。" }
        }
        if phase == "bound" {
            qr = nil
            message = state["accountReady"] as? Bool == false ? "绑定已完成，此工作区尚未完成 Codex 登录。" : state["bridgeConnected"] as? Bool == true && state["cloudConnected"] as? Bool == true ? "工作区已就绪，可在手机使用。" : state["running"] as? Bool == true ? "绑定已完成，正在等待 Codex 或云端连接。" : "绑定已保存，点击工作区的启动服务即可运行。"
        }
    }
    private func cancelBinding() async {
        busy = true
        polling?.cancel(); polling = nil
        defer { busy = false }
        if let state = await exchange(["action":"cancel"]) {
            render(state)
            if phase == "bound" { await model.refresh() }
        } else if phase == "waiting" {
            beginPolling()
        }
    }
    private func beginPolling() {
        polling?.cancel()
        polling = Task {
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
                let response = await exchange(["action":"poll"])
                guard !Task.isCancelled else { return }
                guard let state = response else { phase = "configured"; qr = nil; return }
                render(state)
                if phase == "bound" { await model.refresh(); return }
                if phase == "confirming" { return }
            }
        }
    }
}
