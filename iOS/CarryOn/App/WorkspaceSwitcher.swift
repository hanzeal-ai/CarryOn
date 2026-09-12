import SwiftUI
import CarryOnCore

struct WorkspaceSwitcher: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var help = false
    @State private var details: Record?
    @State private var removal: Record?
    @State private var removed = false
    var body: some View {
        NavigationStack {
            List {
                ForEach(model.devices) { device in
                    Button {
                        model.switchDevice(device.id)
                        dismiss()
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "laptopcomputer")
                            VStack(alignment: .leading, spacing: 5) {
                                Text(device.title).foregroundStyle(Design.ink).lineLimit(1)
                                Text(device.id == model.selectedDevice ? "当前使用" : device.value["online"].bool == true ? "在线" : "离线")
                                    .font(.caption).foregroundStyle(device.id == model.selectedDevice ? Design.green : Design.secondary)
                            }
                            Spacer(minLength: 0)
                        }.frame(maxWidth: .infinity, minHeight: 70).contentShape(Rectangle())
                    }.buttonStyle(.plain)
                    .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                        Button { removal = device } label: {
                            Label("移除", systemImage: "trash")
                        }.tint(.red)
                        Button { details = device } label: {
                            Label("详情", systemImage: "info.circle")
                        }.tint(.gray)
                    }
                    .disabled(model.removingDevice)
                }
                if model.devices.isEmpty { Text("暂无工作区").foregroundStyle(Design.secondary) }
            }
            .scrollContentBackground(.hidden).background(Design.background)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("连接新工作区？") { help = true } }
                ToolbarItem(placement: .topBarTrailing) { Button { dismiss() } label: { Image(systemName: "xmark") }.accessibilityLabel("关闭") }
            }
            .sheet(isPresented: $help) { WorkspaceConnectionHelp() }
            .sheet(item: $details) { WorkspaceDetails(device: $0) }
            .alert("移除此设备？", isPresented: Binding(get: { removal != nil }, set: { if !$0 { removal = nil } })) {
                Button("取消", role: .cancel) { removal = nil }
                Button("移除", role: .destructive) {
                    guard let device = removal else { return }
                    removal = nil
                    Task { do { try await model.removeDevice(device.id); removed = true } catch { model.report(error) } }
                }
            } message: { Text("移除后将撤销此设备的连接凭证，重新接入需在电脑端再次申请。已被 Codex 接收的任务可能仍在执行。") }
            .alert("设备已移除", isPresented: $removed) { Button("好", role: .cancel) {} }
        }.presentationDetents([.medium, .large])
    }
}

struct WorkspaceConnectionHelp: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    private var command: String {
        let url = model.addressText.replacingOccurrences(of: "'", with: "'\\''")
        return "carryon start\ncarryon bridge on\ncarryon cloud connect --url '" + url + "'" + (model.addressText.hasPrefix("http:") ? " --dev-local" : "")
    }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("CLI").font(.headline)
                    Text("1. 在电脑上安装 CarryOn，并打开 Codex App。\n2. 在终端执行以下命令：")
                    WorkspaceCopyBlock(text: command, label: "复制命令", monospaced: true)
                    Text("3. 在本端「我的 → 连接申请」核对设备及两端确认码，确认连接。")
                    Divider()
                    Text("桌面端").font(.headline)
                    Text("1. 打开 CarryOn 桌面端，选择或添加工作区。\n2. 启动服务、开启桥接，点击「连接云端」。\n3. 输入以下云端地址并发起申请：")
                    WorkspaceCopyBlock(text: model.addressText, label: "复制云端地址")
                    Text("4. 在本端「我的 → 连接申请」核对设备及两端确认码，确认连接。")
                    Text("连接默认只读；需要操作会话时，在电脑端允许远程控制。").font(.caption).foregroundStyle(Design.secondary)
                }.padding(20)
            }.navigationTitle("连接新工作区").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { dismiss() } label: { Image(systemName: "xmark") }.accessibilityLabel("关闭") } }
        }.presentationDetents([.large])
    }
}

struct WorkspaceDetails: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let device: Record
    @State private var info: JSONValue = .null
    @State private var failure: String?
    @State private var loading = true
    var body: some View {
        NavigationStack {
            Form {
                LabeledContent("工作区", value: device.title)
                LabeledContent("设备 ID", value: device.id)
                LabeledContent("状态", value: device.value["online"].bool == true ? "在线" : "离线")
                LabeledContent("主机名", value: info["hostname"].string ?? "暂不可用")
                LabeledContent("监听地址", value: info["listenHost"].string ?? "暂不可用")
                LabeledContent("监听端口", value: info["port"].int.map(String.init) ?? "暂不可用")
                if loading { ProgressView("正在读取设备信息") }
                if let failure { Text(failure).font(.caption).foregroundStyle(Design.secondary) }
            }.navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { dismiss() } label: { Image(systemName: "xmark") }.accessibilityLabel("关闭") } }
        }.task {
            defer { loading = false }
            guard device.value["online"].bool == true else { failure = "设备离线，无法读取实时主机信息。"; return }
            do {
                let value = try await model.console("devices/" + ConsoleAddress.component(device.id) + "/request", body: .object(["method": .string("GET"), "path": .string("/api/status")]))
                info = value["deviceInfo"]
                if info.object == nil { failure = "此设备版本尚未提供主机信息。" }
            } catch { failure = error.localizedDescription }
        }
    }
}

private struct WorkspaceCopyBlock: View {
    let text: String
    let label: String
    var monospaced = false
    @State private var copied = false
    @State private var reset: Task<Void, Never>?
    var body: some View {
        Text(text).font(monospaced ? .system(.caption, design: .monospaced) : .body)
            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            .padding(.trailing, 40).padding(16)
            .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
            .overlay(alignment: .topTrailing) {
                Button {
                    UIPasteboard.general.string = text; copied = true; reset?.cancel()
                    reset = Task {
                        do { try await Task.sleep(for: .milliseconds(1800)); copied = false } catch {}
                    }
                } label: { Image(systemName: copied ? "checkmark" : "doc.on.doc").frame(width: 44, height: 44) }
                    .accessibilityLabel(copied ? "已复制" : label)
            }.onDisappear { reset?.cancel(); copied = false }
    }
}
