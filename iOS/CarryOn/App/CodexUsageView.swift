import SwiftUI
import CarryOnCore

struct CodexUsageView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @State private var usage: JSONValue = .null
    @State private var loading = false
    @State private var failure: String?
    @State private var requestVersion = UUID()
    @State private var details = false
    private var windows: [JSONValue] {
        let limits = usage["limits"].array
        let limit = limits.first { $0["id"].text.lowercased() == "codex" || $0["name"].text.lowercased() == "codex" } ?? limits.first
        return Array((limit?["windows"].array ?? []).prefix(2))
    }
    var body: some View {
        Button { details = true } label: {
            HStack(alignment: .top, spacing: 8) {
                if model.connected && failure == nil && !windows.isEmpty {
                    ForEach(windows, id: \.stableID) { window in
                        CodexUsageWindow(window: window, compact: true)
                    }
                } else {
                    VStack(spacing: 4) {
                        ZStack {
                            Circle().stroke(Design.secondary.opacity(0.15), lineWidth: 3)
                            if loading { ProgressView().controlSize(.mini) }
                            else { Text("—").font(.caption).foregroundStyle(Design.secondary) }
                        }.frame(width: 36, height: 36)
                        Text("额度").font(.system(size: 9)).foregroundStyle(Design.secondary)
                    }
                }
            }.padding(4).contentShape(Rectangle())
        }.buttonStyle(.plain)
            .accessibilityLabel("Codex 账号剩余额度，查看详情")
            .popover(isPresented: $details) { usageDetails.presentationCompactAdaptation(.popover) }
            .task(id: model.scope + String(model.connected) + String(scenePhase == .active)) {
                if scenePhase == .active { await load() }
            }
    }
    private var usageDetails: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Codex 额度", systemImage: "chart.bar")
                Spacer()
                Button { Task { await load() } } label: {
                    if loading { ProgressView() } else { Image(systemName: "arrow.clockwise") }
                }.disabled(loading || !model.connected).accessibilityLabel("刷新 Codex 额度")
            }.font(.subheadline)
            if !model.connected { Text("工作区未连接").foregroundStyle(Design.secondary) }
            else if let failure { Text(failure).font(.caption).foregroundStyle(Design.secondary) }
            else if loading { Text("正在读取…").foregroundStyle(Design.secondary) }
            else if usage["limits"].array.isEmpty { Text("暂无可用额度数据").foregroundStyle(Design.secondary) }
            else {
                ForEach(usage["limits"].array, id: \.stableID) { limit in
                    VStack(alignment: .leading, spacing: 12) {
                        if usage["limits"].array.count > 1 || !["codex", ""].contains(limit["name"].text.lowercased()) {
                            Text(limit["name"].text).font(.caption).foregroundStyle(Design.secondary)
                        }
                        ForEach(limit["windows"].array, id: \.stableID) { window in
                            CodexUsageWindow(window: window)
                        }
                    }
                }
                if case .number(let timestamp) = usage["fetchedAt"] {
                    Text("更新于 " + Date(timeIntervalSince1970: timestamp).formatted(date: .omitted, time: .shortened))
                        .font(.caption2).foregroundStyle(Design.secondary)
                }
            }
            Text("当前工作区 Codex 登录账号的共享额度").font(.caption2).foregroundStyle(Design.secondary)
        }.padding(16).frame(idealWidth: 280)
    }
    private func load() async {
        let version = UUID(), scope = model.scope
        requestVersion = version; usage = .null; failure = nil
        guard model.connected, model.device != nil else { loading = false; return }
        loading = true
        defer { if version == requestVersion { loading = false } }
        do {
            let result = try await model.deviceRequest("/api/usage")
            guard !Task.isCancelled, scope == model.scope, version == requestVersion else { return }
            guard case .array = result["limits"] else { throw APIError("额度数据格式不正确") }
            usage = result
        } catch {
            if !Task.isCancelled, scope == model.scope, version == requestVersion {
                failure = (error as? APIError)?.status == 404 ? "本机服务尚不支持额度查询，请更新本机服务" : error.localizedDescription
            }
        }
    }
}

private struct CodexUsageWindow: View {
    let window: JSONValue
    var compact = false
    private var label: String {
        guard let minutes = window["windowDurationMins"].int else { return window["id"].text == "primary" ? "主要额度" : "其他额度" }
        if minutes % 1440 == 0 { return "\(minutes / 1440) 天额度" }
        if minutes % 60 == 0 { return "\(minutes / 60) 小时额度" }
        return "\(minutes) 分钟额度"
    }
    private var remaining: Double? {
        guard case .number(let used) = window["usedPercent"], used.isFinite else { return nil }
        return min(100, max(0, 100 - used))
    }
    var body: some View {
        VStack(spacing: 4) {
            ZStack {
                Circle().stroke(Design.secondary.opacity(0.15), lineWidth: 3)
                if let remaining {
                    Circle().trim(from: 0, to: remaining / 100)
                        .stroke(remaining <= 10 ? Design.orange : Design.ink, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    Text("\(remaining, specifier: "%.0f")%")
                        .font(.system(size: compact ? 10 : 13, weight: .medium)).monospacedDigit()
                } else { Text("—").font(.caption).foregroundStyle(Design.secondary) }
            }.frame(width: compact ? 36 : 48, height: compact ? 36 : 48)
            Text(compact ? label.replacingOccurrences(of: "额度", with: "") : label + " · 剩余")
                .font(.system(size: compact ? 9 : 12)).foregroundStyle(Design.secondary)
            if !compact, case .number(let reset) = window["resetsAt"] {
                Text("重置时间 " + Date(timeIntervalSince1970: reset).formatted(date: .abbreviated, time: .shortened))
                    .font(.caption2).foregroundStyle(Design.secondary)
            }
        }.accessibilityElement(children: .ignore)
            .accessibilityLabel(label + (remaining.map { "，剩余 \(Int($0.rounded()))%" } ?? "，用量未知"))
    }
}
