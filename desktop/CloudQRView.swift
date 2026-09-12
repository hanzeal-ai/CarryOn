import SwiftUI
import CoreImage.CIFilterBuiltins

@MainActor struct CloudQRView: View {
    @ObservedObject var model: SettingsModel
    @Environment(\.dismiss) private var dismiss
    @State private var url: String
    @State private var username = ""
    @State private var password = ""
    @State private var session = ""
    @State private var invitationID = ""
    @State private var image: NSImage?
    @State private var state = ""
    @State private var verification = ""
    @State private var message = ""
    @State private var busy = false
    @State private var decisionRevision = 0
    @State private var poller: Task<Void, Never>?

    init(model: SettingsModel, initialURL: String = "") { self.model = model; _url = State(initialValue: initialURL) }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("手机扫码登录").font(.title2.weight(.semibold))
            if invitationID.isEmpty {
                TextField("云端 HTTPS 地址", text: $url).textFieldStyle(.roundedBorder)
                TextField("云端账号", text: $username).textFieldStyle(.roundedBorder)
                SecureField("云端密码", text: $password).textFieldStyle(.roundedBorder)
            } else {
                Text(url).font(.caption).foregroundStyle(DesktopDesign.secondary).textSelection(.enabled)
                if state == "waiting", let image {
                    Image(nsImage: image).interpolation(.none).resizable().scaledToFit().frame(width: 250, height: 250).padding(16).background(.white).frame(maxWidth: .infinity)
                    Text("用手机扫描，二维码三分钟内有效。").font(.caption).foregroundStyle(DesktopDesign.secondary)
                }
                if state == "scanned" {
                    Text("手机确认码").font(.caption)
                    Text(verification).font(.system(size: 32, weight: .semibold, design: .monospaced))
                    Text("核对与自己手机显示的确认码一致后，允许登录。").font(.caption)
                    HStack {
                        Button("拒绝") { Task { await decide("reject") } }
                        Button("允许登录") { Task { await decide("approve") } }.buttonStyle(AccentButton())
                    }
                }
            }
            if !message.isEmpty { Text(message).font(.caption).foregroundStyle(state == "redeemed" ? DesktopDesign.green : DesktopDesign.secondary) }
            HStack {
                if busy { ProgressView().controlSize(.small) }
                Spacer()
                Button("关闭") { Task { await close(); dismiss() } }.keyboardShortcut(.cancelAction)
                if invitationID.isEmpty {
                    Button("生成二维码") { Task { await create() } }.buttonStyle(AccentButton()).disabled(url.isEmpty || username.isEmpty || password.isEmpty)
                }
            }
        }.padding(28).frame(width: 470).background(DesktopDesign.background).disabled(busy)
            .interactiveDismissDisabled(busy).onDisappear {
                poller?.cancel(); password = ""
                let fields = credentials("close"), target = url
                if !session.isEmpty { Task { _ = await model.qrRequest(url: target, fields: fields) } }
                session = ""
            }
    }
    private func credentials(_ action: String) -> [String: String] { ["action": action, "session": session, "id": invitationID, "verification": verification] }
    private func create() async {
        busy = true; defer { busy = false }
        url = url.trimmingCharacters(in: .whitespacesAndNewlines)
        let result = await model.qrRequest(url: url, fields: ["action": "create", "username": username, "password": password])
        password = ""
        guard result.code == 0, let data = model.object(result.text), let id = data["id"] as? String,
              let token = data["session"] as? String, let link = data["url"] as? String else {
            message = result.code == 0 ? "二维码响应无效" : result.text; return
        }
        invitationID = id; session = token; state = "waiting"; message = ""
        let filter = CIFilter.qrCodeGenerator(); filter.message = Data(link.utf8); filter.correctionLevel = "M"
        guard let output = filter.outputImage, let cg = CIContext().createCGImage(output, from: output.extent) else {
            message = "无法生成二维码"; await close(); return
        }
        image = NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
        poller = Task { await poll() }
    }
    private func poll() async {
        let end = Date().addingTimeInterval(180)
        while !Task.isCancelled && Date() < end {
            do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
            if busy { continue }
            let revision = decisionRevision
            let result = await model.qrRequest(url: url, fields: credentials("status"))
            guard !Task.isCancelled else { return }
            if busy || revision != decisionRevision { continue }
            guard result.code == 0, let data = model.object(result.text), let value = data["state"] as? String else {
                message = result.code == 0 ? "扫码状态无效" : result.text; return
            }
            state = value; verification = data["verification"] as? String ?? ""
            if value == "redeemed" || value == "rejected" {
                message = value == "redeemed" ? "手机已登录" : "已拒绝登录"; image = nil; await close(); return
            }
        }
        if !Task.isCancelled { image = nil; state = "expired"; message = "二维码已过期，请关闭后重新生成"; await close() }
    }
    private func decide(_ action: String) async {
        decisionRevision += 1
        busy = true; defer { busy = false }
        let result = await model.qrRequest(url: url, fields: credentials(action))
        if result.code == 0 {
            state = action == "approve" ? "approved" : "rejected"
            message = action == "approve" ? "已允许，等待手机完成登录" : "已拒绝登录"
        } else { message = result.text; state = "unknown"; poller?.cancel() }
    }
    private func close() async {
        poller?.cancel()
        guard !session.isEmpty else { return }
        let fields = credentials("close"); session = ""
        _ = await model.qrRequest(url: url, fields: fields)
    }
}
