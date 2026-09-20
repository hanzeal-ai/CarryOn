import SwiftUI
import CoreImage.CIFilterBuiltins

@MainActor struct AccountLoginCodeView: View {
    @ObservedObject var model: SettingsModel
    let url: String
    @Environment(\.dismiss) private var dismiss
    @State private var username = ""
    @State private var password = ""
    @State private var invitation: [String: Any] = [:]
    @State private var image: NSImage?
    @State private var verification = ""
    @State private var phase = ""
    @State private var message = ""
    @State private var busy = false
    @State private var polling: Task<Void,Never>?
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("账号登录码").font(.title2.weight(.semibold))
            if invitation.isEmpty {
                TextField("要登录的 CarryOn 账号", text: $username).textContentType(.username)
                SecureField("该账号密码", text: $password).textContentType(.password)
                Button("生成登录码") { Task { await create() } }.buttonStyle(AccentButton()).disabled(busy || username.isEmpty || password.isEmpty)
            } else {
                Text(username).font(.headline)
                if let image { Image(nsImage:image).interpolation(.none).resizable().scaledToFit().frame(width:240,height:240) }
                if phase == "scanned" {
                    Text("核对手机上的六位确认码").font(.callout)
                    TextField("确认码", text: $verification)
                    HStack {
                        Button("拒绝") { Task { _ = await exchange("reject") } }
                        Button("允许登录") { Task { _ = await exchange("approve", extra:["verification":verification]) } }.disabled(verification.count != 6)
                    }
                }
                if phase == "redeemed" { Text("手机已登录") }
            }
            if !message.isEmpty { Text(message).font(.caption).foregroundStyle(.red) }
            HStack { Spacer(); Button("关闭") { dismiss() } }
        }.textFieldStyle(.roundedBorder).padding(28).frame(width:430)
            .onDisappear {
                polling?.cancel()
                let data = invitation
                Task { if !data.isEmpty { _ = await exchange("close", extra:data) } }
            }
    }
    private func exchange(_ action: String, extra: [String:Any] = [:]) async -> [String:Any]? {
        var fields = invitation; fields.merge(extra) { _,new in new }; fields["action"] = action
        guard let input = try? JSONSerialization.data(withJSONObject:fields) else { return nil }
        let directory = model.directory
        let result = await Task.detached { executeCLI(["cloud","qr","--url",url,"--input-json"],directory:directory,input:input) }.value
        guard result.code == 0, let value = model.object(result.text) else { message = "无法完成扫码登录，请重新生成或核对账号密码。"; return nil }
        return value
    }
    private func create() async {
        busy = true; defer { busy = false }
        guard let value = await exchange("create",extra:["username":username,"password":password]), let raw = value["url"] as? String else { return }
        password = ""; invitation = value
        let generator = CIFilter.qrCodeGenerator(); generator.message = Data(raw.utf8)
        if let output = generator.outputImage, let cg = CIContext().createCGImage(output, from:output.extent) { image = NSImage(cgImage:cg,size:NSSize(width:cg.width,height:cg.height)) }
        polling = Task {
            for _ in 0..<120 {
                do { try await Task.sleep(nanoseconds:1_500_000_000) } catch { return }
                guard let value = await exchange("status") else { image = nil; invitation = [:]; return }
                phase = value["state"] as? String ?? ""
                if ["redeemed","rejected"].contains(phase) { image = nil; return }
            }
            image = nil; invitation = [:]; message = "登录码已过期，请重新生成。"
        }
    }
}
