import SwiftUI
import AppKit

@MainActor struct RegistrationInviteView: View {
    @ObservedObject var model: SettingsModel
    let bindingID: String
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var issuerHash = ""
    @State private var message = ""
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("注册邀请码").font(.title2.weight(.semibold))
            if !code.isEmpty {
                Text(code).font(.body.monospaced()).textSelection(.enabled)
                Text("注册成功后失效，仅可使用一次。").font(.caption).foregroundStyle(DesktopDesign.secondary)
                Button("复制邀请码") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(code, forType: .string)
                }
            }
            if !message.isEmpty { Text(message).font(.caption).foregroundStyle(.red).textSelection(.enabled) }
            if !issuerHash.isEmpty {
                Text("本机授权指纹").font(.caption)
                Text(issuerHash).font(.caption.monospaced()).textSelection(.enabled)
            }
            HStack {
                Button("本机授权指纹") { Task { await run(setup: true) } }.buttonStyle(QuietButton())
                Spacer()
                if busy { ProgressView().controlSize(.small) }
                Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("生成邀请码") { Task { await run(setup: false) } }.buttonStyle(AccentButton())
            }
        }.padding(28).frame(width: 540).background(DesktopDesign.background).disabled(busy)
    }

    private func run(setup: Bool) async {
        busy = true; message = ""
        defer { busy = false }
        let directory = model.directory
        let arguments = setup ? ["invate", "--setup"] : ["invate", "--binding-id", bindingID]
        let result = await Task.detached { executeCLI(arguments, directory: directory) }.value
        guard result.code == 0, let value = model.object(result.text) else { message = result.text; return }
        if setup { issuerHash = value["issuerHash"] as? String ?? "" }
        else { code = value["inviteCode"] as? String ?? "" }
    }
}
