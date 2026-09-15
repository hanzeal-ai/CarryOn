import SwiftUI
import AppKit

@MainActor struct SettingsView: View {
    @StateObject var model: SettingsModel
    @ObservedObject private var foreground = ForegroundServices.shared
    @State private var page = "overview"
    @State private var adding = false
    @State private var connecting = false
    @State private var stopping = false
    @State private var removing: CloudBinding?
    @State private var controllerInput = ""
    @State private var initializing = false
    @State private var setupRequired = false
    @State private var membersBinding: CloudBinding?

    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 256)
            Rectangle().fill(DesktopDesign.line).frame(width: 1)
            VStack(spacing: 0) {
                header
                ScrollView {
                    VStack(spacing: 0) {
                        if !model.catalogError.isEmpty { notice(model.catalogError, error: true) }
                        if page == "overview" { overview }
                        else if page == "diagnostics" { diagnostics }
                        else { logs }
                    }.frame(maxWidth: 780).padding(.horizontal, 30).padding(.bottom, 28).frame(maxWidth: .infinity)
                }
                if !model.message.isEmpty {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: model.messageIsError ? "exclamationmark.circle" : "checkmark.circle")
                        Text(model.message).font(.system(size: 12)).textSelection(.enabled).lineLimit(4)
                        Spacer()
                        Button { model.message = "" } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
                    }.foregroundStyle(model.messageIsError ? Color.red : DesktopDesign.secondary).padding(15).background(.white)
                }
            }
        }
        .background(DesktopDesign.background).foregroundStyle(DesktopDesign.ink).tint(DesktopDesign.blue)
        .frame(minWidth: 960, minHeight: 700).preferredColorScheme(.light)
        .sheet(isPresented: $initializing, onDismiss: { Task { await refreshSetup() } }) { InitializationView(model: model).id(model.directory) }
        .sheet(item: $membersBinding) { WorkspaceMembersView(model: model, bindingID: $0.id).id(model.directory) }
        .sheet(isPresented: $adding, onDismiss: { Task { await refreshSetup() } }) { WorkspaceSetupView(model: model) }
        .sheet(isPresented: $connecting) { ConnectCloudView(model: model, initialURL: model.linkURL).id(model.directory) }
        .alert("停止「\(model.selectedName)」的服务？", isPresented: $stopping) {
            Button("取消", role: .cancel) {}
            Button("停止服务", role: .destructive) { Task { await model.perform(["stop"]) } }
        } message: { Text("仅停止此工作区的服务和云端连接。Codex 已接收的任务会继续执行。") }
        .alert("解除云端绑定？", isPresented: Binding(get: {removing != nil}, set: {if !$0 {removing = nil}})) {
            Button("取消", role: .cancel) { removing = nil }
            Button("解除绑定", role: .destructive) {
                if let binding = removing { Task { await model.perform(["cloud", "disconnect", "--binding-id", binding.id]) } }
                removing = nil
            }
        } message: { Text(removing?.url ?? "") }
        .task {
            await model.refresh()
            await refreshSetup(autoOpen: true)
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 4_000_000_000) } catch { return }
                await model.refresh()
                await refreshSetup()
            }
        }
        .onChange(of: model.directory) { _ in controllerInput = ""; page = "overview"; setupRequired = false; Task { await refreshSetup() } }
    }
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image("CarryOnLogo").resizable().scaledToFit().frame(width: 36, height: 36).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) { Text("CarryOn").font(.system(size: 18, weight: .semibold)); Text("换个设备，接着做。").font(.system(size: 10)).foregroundStyle(DesktopDesign.secondary) }
            }.padding(.horizontal, 23).padding(.top, 30).padding(.bottom, 32)
            HStack { Text("本地工作区").font(.system(size: 11, weight: .medium)); Spacer(); Text("\(model.services.filter(\.running).count) 个运行中").font(.system(size: 10)) }
                .foregroundStyle(DesktopDesign.secondary).padding(.horizontal, 23).padding(.bottom, 12)
            ScrollView {
                VStack(spacing: 7) {
                    ForEach(model.services) { service in
                        Button { Task { await model.select(service) } } label: {
                            HStack(alignment: .top, spacing: 11) {
                                Image(systemName: "laptopcomputer").font(.system(size: 20)).foregroundStyle(service.directory == model.directory ? DesktopDesign.blue : DesktopDesign.secondary).padding(.top, 3)
                                VStack(alignment: .leading, spacing: 7) {
                                    Text(service.name).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                                    Text(shortPath(service.directory)).font(.system(size: 10)).foregroundStyle(DesktopDesign.secondary).lineLimit(1).truncationMode(.middle)
                                    HStack(spacing: 5) { Circle().fill(service.running ? DesktopDesign.green : DesktopDesign.secondary).frame(width: 5, height: 5); Text(service.label + (service.running ? " · \(service.port)" : "")).font(.system(size: 10)).foregroundStyle(DesktopDesign.secondary) }
                                }; Spacer(minLength: 0)
                            }.padding(13).frame(maxWidth: .infinity, alignment: .leading)
                                .background(service.directory == model.directory ? Color.white : Color.clear, in: RoundedRectangle(cornerRadius: 13))
                                .overlay(RoundedRectangle(cornerRadius: 13).stroke(service.directory == model.directory ? DesktopDesign.blue.opacity(0.15) : .clear, lineWidth: 1))
                        }.buttonStyle(.plain).disabled(model.busy)
                    }
                }.padding(.horizontal, 12)
            }
            Button { adding = true } label: { Label("添加工作区", systemImage: "plus").frame(maxWidth: .infinity).frame(height: 38) }
                .buttonStyle(QuietButton()).padding(18).disabled(model.busy)
            Text("CLI 启动的服务会自动出现在这里").font(.system(size: 10)).foregroundStyle(DesktopDesign.secondary).padding(.horizontal, 23).padding(.bottom, 22)
        }.background(DesktopDesign.background)
    }
    private var header: some View {
        HStack {
            HStack(spacing: 7) {
                tab("工作区", id: "overview")
                tab("诊断", id: "diagnostics")
                tab("运行日志", id: "logs")
            }
            Spacer()
            if model.busy { ProgressView().controlSize(.small) }
            Button { Task { await model.refresh() } } label: { Image(systemName: "arrow.clockwise").frame(width: 28, height: 28) }
                .buttonStyle(.plain).foregroundStyle(DesktopDesign.secondary).help("刷新状态 · carryon status").disabled(model.busy)
        }.padding(.horizontal, 30).padding(.vertical, 17)
    }
    private func tab(_ title: String, id: String) -> some View {
        Button { page = id } label: { Text(title).font(.system(size: 12, weight: page == id ? .semibold : .regular)).padding(.horizontal, 15).padding(.vertical, 8)
            .foregroundStyle(page == id ? DesktopDesign.ink : DesktopDesign.secondary).background(page == id ? .white : .clear, in: Capsule()) }.buttonStyle(.plain)
    }
    private var overview: some View {
        VStack(spacing: 0) {
            Paper {
                VStack(spacing: 13) {
                    Image(systemName: "laptopcomputer").font(.system(size: 48, weight: .ultraLight)).foregroundStyle(DesktopDesign.secondary)
                    Text(model.selectedName).font(.system(size: 23, weight: .semibold))
                    Text(shortPath(model.directory)).font(.system(size: 11)).foregroundStyle(DesktopDesign.secondary).textSelection(.enabled)
                    StatePill(label: model.running ? "服务运行中 · \(model.port)" : "服务未运行", active: model.running)
                    HStack(spacing: 10) {
                        if model.running {
                            Button("打开会话") { Task { await model.perform(["open"]) } }.buttonStyle(AccentButton()).help("carryon open")
                            Button("停止服务") { stopping = true }.buttonStyle(QuietButton()).help("carryon stop")
                        } else {
                            Button("启动服务") { Task { await model.perform(["start", "--no-open", "--port", model.port, "--codex-home", model.codexHome]) } }.buttonStyle(AccentButton()).help("后台启动 · carryon start")
                        }
                    }.padding(.top, 5).disabled(model.busy)
                }.padding(25).frame(maxWidth: .infinity)
            }
            if setupRequired {
                Paper {
                    SettingRow(icon: "qrcode", title: "工作区设置未完成") {
                        Button("继续设置") { initializing = true }.buttonStyle(AccentButton()).disabled(model.busy)
                    }
                }.padding(.top, 16)
            }
            SectionCaption(title: "连接与访问")
            Paper {
                SettingRow(icon: "cable.connector", title: "Codex 连接") {
                    StatePill(label: model.enabled ? "已连接" : model.bridgeRequested ? "等待 Codex" : "未连接", active: model.enabled)
                }
                RowDivider()
                SettingRow(icon: "moon", title: "远程待机", detail: model.standbyDescription) {
                    Toggle("远程待机", isOn: Binding(get: {model.standby}, set: {v in Task { await model.perform(["standby", v ? "on" : "off"]) } })).labelsHidden().toggleStyle(.switch).controlSize(.small)
                }
            }.disabled(!model.running || model.busy)
            HStack {
                SectionCaption(title: "云端连接"); Spacer()
                if !model.bindings.isEmpty {
                    Menu { Button("连接其他云端") { connecting = true } } label: { Image(systemName: "ellipsis") }
                        .menuStyle(.borderlessButton).frame(width: 24).padding(.top, 14).disabled(!model.running || model.busy)
                }
            }
            Paper {
                if model.bindings.isEmpty {
                    SettingRow(icon: "icloud", title: "尚未绑定", detail: "完成工作区设置后连接") { EmptyView() }
                }
                ForEach(model.bindings) { binding in
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 12) {
                            SymbolTile(name: "icloud", color: DesktopDesign.blue)
                            VStack(alignment: .leading, spacing: 5) { Text(binding.url).font(.system(size: 12, weight: .medium)).textSelection(.enabled); StatePill(label: binding.connected ? "已连接" : "等待连接", active: binding.connected) }
                            Spacer()
                            Menu { Button("解除绑定", role: .destructive) { removing = binding } } label: { Image(systemName: "ellipsis") }.menuStyle(.borderlessButton).frame(width: 24)
                        }
                        Button("使用者与权限") { membersBinding = binding }.buttonStyle(QuietButton()).disabled(model.busy)
                        HStack {
                            Text("允许远程控制").font(.system(size: 12)); Spacer()
                            Toggle("允许此云端远程控制", isOn: Binding(get: {binding.control}, set: {v in Task { await model.perform(["cloud", "control", "--binding-id", binding.id, v ? "--allow-control" : "--read-only"]) } })).labelsHidden().toggleStyle(.switch).controlSize(.small)
                        }.padding(.leading, 48)
                        if !binding.error.isEmpty { Text(binding.error).font(.caption).foregroundStyle(.red) }
                    }.padding(16).disabled(model.busy)
                    if binding.id != model.bindings.last?.id { RowDivider() }
                }
            }
            if !model.linkDescription.isEmpty {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: model.linkIsError ? "exclamationmark.circle.fill" : "info.circle")
                    Text(model.linkDescription).font(.system(size: 12)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    if model.linkCanRetry {
                        Button("重新申请") { connecting = true }.buttonStyle(QuietButton()).disabled(!model.running || model.busy)
                    }
                }.foregroundStyle(model.linkIsError ? Color.red : DesktopDesign.secondary)
                    .padding(14).background((model.linkIsError ? Color.red : DesktopDesign.blue).opacity(0.06), in: RoundedRectangle(cornerRadius: 12)).padding(.top, 10)
            }
            SectionCaption(title: "任务与通知")
            Paper {
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(model.controller.isEmpty ? "尚未选定控制会话" : model.controller).font(.caption).textSelection(.enabled)
                        HStack { TextField("已加载的空闲会话 ID", text: $controllerInput); Button("保存") { Task { await model.perform(["controller", "set", "--thread-id", controllerInput]) } }.buttonStyle(QuietButton()).disabled(controllerInput.isEmpty) }
                    }.padding(14)
                } label: { Label("创建任务的控制会话", systemImage: "bubble.left.and.bubble.right").font(.system(size: 13)) }.padding(16).disabled(!model.enabled || model.busy)
                RowDivider()
                DisclosureGroup {
                    ForEach(["message", "done", "failed", "approval"], id: \.self) { kind in
                        Toggle(["message":"新消息", "done":"任务完成", "failed":"执行失败", "approval":"需要确认"][kind]!, isOn: Binding(get: {model.preferences[kind] ?? true}, set: {v in Task { await model.perform(["notifications", "set", v ? "--"+kind : "--no-"+kind]) } })).toggleStyle(.switch).controlSize(.small).padding(10)
                    }
                } label: { Label("消息通知", systemImage: "bell").font(.system(size: 13)) }.padding(16).disabled(!model.enabled || model.preferences.isEmpty || model.busy)
            }
        }
    }
    private func refreshSetup(autoOpen: Bool = false) async {
        if !autoOpen && (initializing || adding || model.busy) { return }
        let target = model.directory
        let result = await Task.detached {
            executeCLI(["init", "--input-json"], directory: target, input: Data("{\"action\":\"status\"}".utf8))
        }.value
        guard target == model.directory, !Task.isCancelled else { return }
        guard result.code == 0, let phase = model.object(result.text)?["state"] as? String else {
            model.message = result.text; model.messageIsError = true; return
        }
        setupRequired = phase != "bound"
        if autoOpen && setupRequired && !adding { initializing = true }
    }
    private var diagnostics: some View {
        VStack(spacing: 0) {
            Paper {
                SettingRow(icon: "waveform.path.ecg", title: "工作区诊断", detail: "检查本机环境、Codex 与当前服务") { Button("运行诊断") { Task { await model.diagnose() } }.buttonStyle(AccentButton()).disabled(model.busy).help("carryon doctor") }
                ForEach(["supportedPlatform", "ipcSocketAvailable", "databaseAvailable"], id: \.self) { key in
                    RowDivider()
                    SettingRow(icon: key == "ipcSocketAvailable" ? "cable.connector" : key == "databaseAvailable" ? "externaldrive" : "laptopcomputer", title: ["supportedPlatform":"系统支持", "ipcSocketAvailable":"Codex 连接", "databaseAvailable":"会话数据库"][key]!) {
                        Text((model.diagnostics[key] as? Bool).map {$0 ? "正常" : "需处理"} ?? "未检测").font(.system(size: 12)).foregroundStyle((model.diagnostics[key] as? Bool) == true ? DesktopDesign.green : DesktopDesign.secondary)
                    }
                }
            }
            SectionCaption(title: "高级设置")
            Paper {
                SettingRow(icon: "cable.connector", title: "Codex 桥接", detail: "启动服务时自动连接；可在此单独关闭") {
                    Toggle("Codex 桥接", isOn: Binding(get: {model.bridgeRequested}, set: {value in Task { await model.perform(["bridge", value ? "on" : "off"]) } }))
                        .labelsHidden().toggleStyle(.switch).controlSize(.small)
                }.disabled(!model.running || model.busy)
                if !model.running {
                    RowDivider()
                    SettingRow(icon: "network", title: "启动端口", detail: "0 表示自动分配") {
                        TextField("0", text: $model.port).frame(width: 80)
                    }.disabled(model.busy)
                }
            }
            SectionCaption(title: "当前服务 · status")
            Paper {
                SettingRow(icon: "folder", title: "数据目录") { Text(shortPath(model.directory)).font(.caption).textSelection(.enabled) }
                RowDivider()
                SettingRow(icon: "externaldrive", title: "Codex 目录") {
                    if model.running { Text(shortPath(model.codexHome)).font(.caption).textSelection(.enabled) }
                    else { TextField("~/.codex", text: $model.codexHome).frame(maxWidth: 330) }
                }
                RowDivider()
                SettingRow(icon: "network", title: "服务端口", detail: model.processID.map {"进程 \($0)"} ?? "") { Text(model.running ? model.port : "未运行").font(.caption.monospaced()) }
            }
            if !model.diagnosticText.isEmpty {
                SectionCaption(title: "诊断结果")
                Paper { Text(model.diagnosticText).font(.system(size: 11, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(18) }
            }
        }
    }
    private var logs: some View {
        VStack(spacing: 0) {
            Paper {
                SettingRow(icon: "terminal", title: "前台运行", detail: "服务输出显示在这里；退出桌面应用时停止前台服务。") {
                    Button("前台启动") { Task { await model.serve() } }.buttonStyle(AccentButton()).disabled(model.running || model.busy).help("carryon serve")
                }
            }
            SectionCaption(title: "\(model.selectedName) · 实时输出")
            Paper { Text(foreground.logs[model.directory] ?? "还没有前台运行记录。后台运行的工作区不受关闭窗口影响。")
                .font(.system(size: 12, design: .monospaced)).foregroundStyle(DesktopDesign.secondary).textSelection(.enabled).frame(maxWidth: .infinity, minHeight: 260, alignment: .topLeading).padding(20) }
        }
    }
    private func notice(_ text: String, error: Bool = false) -> some View { Text(text).font(.system(size: 12)).foregroundStyle(error ? Color.red : DesktopDesign.secondary).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled).padding(14) }
    private func shortPath(_ path: String) -> String { path.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~", options: .anchored) }
}

@MainActor struct WorkspaceSetupView: View {
    @ObservedObject var model: SettingsModel
    @Environment(\.dismiss) private var dismiss
    @State private var configured = false
    @State private var name = "新工作区"
    @State private var path = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/CarryOn/Workspaces/" + String(UUID().uuidString.prefix(8))).path
    @State private var port = "0"
    @State private var codex = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex").path
    var body: some View {
        if configured { InitializationView(model: model).id(model.directory) } else {
        VStack(alignment: .leading, spacing: 20) {
            HStack { SymbolTile(name: "plus", color: DesktopDesign.blue); Text("添加工作区").font(.title2.weight(.semibold)) }
            Text("创建新的服务目录，或选择已有目录接入。已有服务会被识别并保留。").font(.system(size: 13)).foregroundStyle(DesktopDesign.secondary)
            VStack(alignment: .leading, spacing: 10) {
                Text("名称").font(.caption); TextField("工作区名称", text: $name)
                DisclosureGroup("高级设置") {
                Text("数据目录").font(.caption)
                HStack { TextField("服务配置保存位置", text: $path); Button("选择…") {
                    let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true; panel.allowsMultipleSelection = false
                    if panel.runModal() == .OK, let url = panel.url { path = url.path; if name == "新工作区" {name = url.lastPathComponent} }
                } }
                HStack { VStack(alignment: .leading) { Text("端口（0 为自动分配）").font(.caption); TextField("0", text: $port) }.frame(width: 165)
                    VStack(alignment: .leading) { Text("Codex 目录").font(.caption); TextField("~/.codex", text: $codex) } }
                }
            }.textFieldStyle(.roundedBorder)
            if model.messageIsError { Text(model.message).font(.caption).foregroundStyle(.red) }
            HStack { Spacer(); Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("下一步") { Task { if await model.add(name: name.trimmingCharacters(in: .whitespacesAndNewlines), path: path, port: port, codex: codex) { configured = true } } }.buttonStyle(AccentButton())
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || path.isEmpty || codex.isEmpty || !(0...65535).contains(Int(port) ?? -1))
            }
        }.padding(28).frame(width: 560).background(DesktopDesign.background).disabled(model.busy)
        }
    }
}
@MainActor struct ConnectCloudView: View {
    @ObservedObject var model: SettingsModel
    @Environment(\.dismiss) private var dismiss
    @State private var url: String
    init(model: SettingsModel, initialURL: String = "") {
        self.model = model; _url = State(initialValue: initialURL)
    }
    @State private var control = false
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack { SymbolTile(name: "icloud", color: DesktopDesign.blue); Text("连接云端").font(.title2.weight(.semibold)) }
            Text("\(model.selectedName) · 发起连接申请").font(.system(size: 13)).foregroundStyle(DesktopDesign.secondary)
            TextField("https://你的云端地址/carryon", text: $url).textFieldStyle(.roundedBorder)
            Toggle("允许远程控制", isOn: $control).toggleStyle(.switch)
            Text("默认只读。申请后，在云端核对确认码并确认连接。").font(.caption).foregroundStyle(DesktopDesign.secondary)
            if model.messageIsError { Text(model.message).font(.caption).foregroundStyle(.red) }
            HStack { Spacer(); Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("申请连接") { Task { var args = ["cloud", "connect", "--url", url.trimmingCharacters(in: .whitespacesAndNewlines)]; if control { args.append("--allow-control") }; await model.perform(args); if !model.messageIsError { dismiss() } } }.buttonStyle(AccentButton()).disabled(url.isEmpty)
            }
        }.padding(28).frame(width: 470).background(DesktopDesign.background).disabled(model.busy)
    }
}
