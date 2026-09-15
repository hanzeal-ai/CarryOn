import SwiftUI
import CoreImage.CIFilterBuiltins

@MainActor struct WorkspaceMembersView: View {
    @ObservedObject var model: SettingsModel
    let bindingID: String
    var rebind: (() -> Void)? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var members: [[String: Any]] = []
    @State private var knownAccounts: [[String: Any]] = []
    @State private var selected = ""
    @State private var permissions: Set<String> = ["view"]
    @State private var invitation: [String: Any]?
    @State private var candidate: [String: Any]?
    @State private var image: NSImage?
    @State private var busy = false
    @State private var message = ""
    @State private var revoking = false
    @State private var poller: Task<Void, Never>?
    private let fields = [("view","查看会话"),("create","新建会话"),("send","发送消息"),("stop","停止任务"),("edit","编辑会话与设置"),("files","查看和下载文件"),("approve","处理审批")]
    private var isMember: Bool { members.contains { ($0["account"] as? [String: Any])?["id"] as? String == selected } }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("工作区使用者").font(.title2.weight(.semibold))
            if invitation == nil {
                Picker("账号", selection: $selected) {
                    Text("邀请新账号").tag("")
                    ForEach(members.indices, id: \.self) { index in
                        let account = members[index]["account"] as? [String:Any] ?? [:]
                        Text(account["username"] as? String ?? "").tag(account["id"] as? String ?? "")
                    }
                    ForEach(knownAccounts.indices, id: \.self) { index in
                        let account = knownAccounts[index]
                        if !members.contains(where: { ($0["account"] as? [String: Any])?["id"] as? String == account["id"] as? String }) {
                            Text((account["username"] as? String ?? "") + "（已确认账号）").tag(account["id"] as? String ?? "")
                        }
                    }
                }.onChange(of: selected) { _ in
                    permissions = Set(members.first(where: { ($0["account"] as? [String:Any])?["id"] as? String == selected })?["permissions"] as? [String] ?? ["view"])
                }
                Button("从已确认账号选择") { Task {
                    busy = true; defer { busy = false }
                    if let result = await exchange(["action":"known-accounts"]) {
                        knownAccounts = result["accounts"] as? [[String: Any]] ?? []
                        message = (result["warnings"] as? [String] ?? []).joined(separator: "\n")
                        if knownAccounts.isEmpty && message.isEmpty { message = "此云端暂无其他已确认账号。" }
                    }
                } }
                ForEach(fields, id: \.0) { key, label in
                    Toggle(label, isOn: Binding(get: { permissions.contains(key) }, set: { value in
                        if value { permissions.insert(key); permissions.insert("view") } else { permissions.remove(key) }
                    })).disabled(key == "view")
                }
            } else if let candidate {
                Text("核对使用者账号").font(.headline)
                Text(candidate["username"] as? String ?? "").font(.title3)
                Text(candidate["id"] as? String ?? "").font(.caption.monospaced()).foregroundStyle(DesktopDesign.secondary)
                Button("确认授权") { Task { await confirm() } }.buttonStyle(AccentButton())
            } else if let image {
                Image(nsImage: image).interpolation(.none).resizable().scaledToFit().frame(width: 240, height: 240).padding(16).background(.white)
                Text("请使用者登录自己的账号后扫码接受，再在这里核对并确认。").font(.callout)
            }
            if !message.isEmpty { Text(message).font(.caption).foregroundStyle(DesktopDesign.secondary).textSelection(.enabled) }
            if let rebind, !message.isEmpty {
                Button("检查绑定") { rebind(); dismiss() }.buttonStyle(QuietButton())
            }
            HStack {
                if busy { ProgressView().controlSize(.small) }
                if isMember && invitation == nil { Button("撤销授权", role: .destructive) { revoking = true } }
                Spacer()
                Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction)
                if invitation == nil {
                    Button(selected.isEmpty ? "生成邀请二维码" : isMember ? "保存权限" : "确认授权") { Task { await save() } }.buttonStyle(AccentButton())
                }
            }
        }.padding(28).frame(width: 470).background(DesktopDesign.background).disabled(busy)
            .task { await load() }.onDisappear { poller?.cancel() }
            .alert("撤销此账号的工作区权限？", isPresented: $revoking) {
                Button("取消", role: .cancel) {}
                Button("撤销授权", role: .destructive) { Task { if await exchange(["action":"revoke","accountId":selected]) != nil { selected = ""; await load() } } }
            } message: { Text("阻止后续访问，不会撤销已执行的任务，也不保证停止正在执行的任务。") }
    }
    private func exchange(_ fields: [String: Any]) async -> [String: Any]? {
        var fields = fields; fields["bindingId"] = bindingID
        guard let data = try? JSONSerialization.data(withJSONObject: fields) else { return nil }
        let target = model.directory
        let result = await Task.detached { executeCLI(["members","--input-json"], directory: target, input: data) }.value
        guard !Task.isCancelled else { return nil }
        guard result.code == 0, let value = model.object(result.text) else { message = result.text; return nil }
        return value
    }
    private func load() async {
        if let result = await exchange(["action":"list"]) { members = result["members"] as? [[String:Any]] ?? [] }
    }
    private func save() async {
        busy = true; defer { busy = false }
        if selected.isEmpty {
            message = ""
            guard let result = await exchange(["action":"invite","permissions":permissions.sorted()]) else { return }
            guard let url = result["url"] as? String, let id = result["id"] as? String,
                  let secret = result["secret"] as? String else { message = "邀请响应无效"; return }
            let filter = CIFilter.qrCodeGenerator(); filter.message = Data(url.utf8)
            guard let output = filter.outputImage, let cg = CIContext().createCGImage(output, from: output.extent) else {
                message = "无法生成二维码，请重试"; return
            }
            image = NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
            invitation = result
            poller?.cancel()
            poller = Task {
                while !Task.isCancelled {
                    do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
                    guard let state = await exchange(["action":"poll","id":id,"secret":secret]) else { invitation = nil; image = nil; return }
                    if state["state"] as? String == "accepted" { candidate = state["account"] as? [String:Any]; return }
                }
            }
        } else {
            var fields: [String: Any] = ["action":"grant","accountId":selected,"permissions":permissions.sorted()]
            if !isMember, let source = knownAccounts.first(where: { $0["id"] as? String == selected }) {
                fields["sourceDirectory"] = source["sourceDirectory"]
                fields["sourceBindingId"] = source["sourceBindingId"]
            }
            if await exchange(fields) != nil { message = "权限已保存"; await load() }
        }
    }
    private func confirm() async {
        guard let invitation, let candidate, let id = invitation["id"] as? String,
              let secret = invitation["secret"] as? String, let account = candidate["id"] as? String else { return }
        busy = true; defer { busy = false }
        if await exchange(["action":"confirm","id":id,"secret":secret,"accountId":account]) != nil {
            self.invitation = nil; self.candidate = nil; image = nil; message = "权限已授予"; await load()
        }
    }
}
