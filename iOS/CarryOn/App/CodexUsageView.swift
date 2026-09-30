import SwiftUI
import CarryOnCore

struct CodexUsageView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    private var usage: JSONValue { model.cachedValue("/api/usage") }
    @State private var loading = false
    @State private var failure: String?
    @State private var requestVersion = UUID()
    @State private var details = false
    @State private var confirmingReset = false
    @State private var confirmedAccount = ""
    @State private var confirmedEpoch = UUID()
    @State private var resetNotice: String?
    private var accountKey: String { usage["accountKey"].text }
    private var resetPending: Bool { model.hasPendingQuotaReset(accountKey: accountKey) }

    private var windows: [JSONValue] {
        let limits = usage["limits"].array
        let limit = limits.first { $0["id"].text.lowercased() == "codex" || $0["name"].text.lowercased() == "codex" } ?? limits.first
        return Array((limit?["windows"].array ?? []).prefix(2))
    }
    private var summaryReset: String? {
        // The long-period limit supplies the summary date; details retain every window.
        guard let window = windows.max(by: { ($0["windowDurationMins"].int ?? 0) < ($1["windowDurationMins"].int ?? 0) }) else { return nil }
        return usageResetText(window)
    }
    var body: some View {
        HStack(spacing: 8) {
            (Text("Codex剩余额度") + Text(summaryReset.map { "（" + $0 + "）" } ?? "").font(.caption2).foregroundColor(Design.secondary))
                .font(.subheadline).lineLimit(1).minimumScaleFactor(0.7).layoutPriority(1)
            Spacer(minLength: 0)
            usageButton
        }
    }
    private var usageButton: some View {
        Button { details = true } label: {
            HStack(spacing: 8) {
                if !windows.isEmpty {
                    ForEach(windows, id: \.stableID) { window in
                        CodexUsageWindow(window: window, compact: true)
                    }
                } else {
                    VStack(spacing: 4) {
                        ZStack {
                            Circle().stroke(Design.secondary.opacity(0.15), lineWidth: 3)
                            if loading { ProgressView().controlSize(.mini) }
                            else {
                                VStack(spacing: 0) {
                                    Text("—").font(.caption)
                                    Text("额度").font(.system(size: 9))
                                }.foregroundStyle(Design.secondary)
                            }
                        }.frame(width: 44, height: 44)
                    }
                }
            }.fixedSize().contentShape(Rectangle())
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
                Text("Codex 额度").fontWeight(.medium)
                Spacer()
                Button { Task { await load(force: true) } } label: {
                    if loading { ProgressView() } else { Image(systemName: "arrow.clockwise") }
                }.disabled(loading || !model.connected).accessibilityLabel("刷新 Codex 额度")
            }.font(.subheadline)
            if !model.connected { Text("工作区未连接").foregroundStyle(Design.secondary) }
            else if let failure { Text(failure).font(.caption).foregroundStyle(Design.secondary) }
            else if loading && usage == .null { Text("正在读取…").foregroundStyle(Design.secondary) }
            else if usage["limits"].array.isEmpty { Text("暂无可用额度数据").foregroundStyle(Design.secondary) }
            else {
                ForEach(usage["limits"].array, id: \.stableID) { limit in
                    VStack(alignment: .leading, spacing: 10) {
                        if usage["limits"].array.count > 1 || !["codex", ""].contains(limit["name"].text.lowercased()) {
                            Text(limit["name"].text).font(.caption).foregroundStyle(Design.secondary)
                        }
                        ForEach(limit["windows"].array, id: \.stableID) { window in
                            CodexUsageWindow(window: window)
                        }
                    }
                }
            }
            if model.connected && failure == nil {
                Divider()
                resetCreditsDetails
                Button(resetPending ? "核对并重试重置" : "使用 1 张重置卡") {
                    confirmedAccount = accountKey; confirmedEpoch = model.epoch
                    confirmingReset = true
                }.disabled(!model.canWrite(.resetQuota) || loading || accountKey.isEmpty ||
                           (!resetPending && (usage["rateLimitResetCredits"]["availableCount"].int ?? 0) < 1))
                if !model.allows(.resetQuota) {
                    Text("需工作区授权使用额度重置卡").font(.caption2).foregroundStyle(Design.secondary)
                } else if accountKey.isEmpty {
                    Text("无法核对账号，请刷新额度后重试").font(.caption2).foregroundStyle(Design.secondary)
                }
            }
            if let resetNotice { Text(resetNotice).font(.caption).foregroundStyle(Design.secondary) }
        }.padding(16).frame(idealWidth: 300)
            .confirmationDialog("使用额度重置卡？", isPresented: $confirmingReset, titleVisibility: .visible) {
                Button(resetPending ? "核对并重试" : "确认使用 1 张", role: .destructive) {
                    Task { await redeem() }
                }
                Button("取消", role: .cancel) {}
            } message: {
                Text("将为当前工作区登录的 Codex 账号使用 1 张卡，重置符合条件的额度。操作无法撤销；结果未确认时会沿用原请求，避免重复消耗。")
            }
    }
    private var resetCreditsDetails: some View {
        let summary = usage["rateLimitResetCredits"]
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("额度重置卡").font(.subheadline)
                Spacer()
                Text(summary["availableCount"].int.map { "\($0) 张可用" } ?? "数量未知")
                    .font(.subheadline).foregroundStyle(Design.secondary)
            }
            ForEach(summary["credits"].array, id: \.stableID) { credit in
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(credit["title"].string ?? "额度重置卡")
                        Spacer()
                        Text(["available": "可用", "redeeming": "兑换中", "redeemed": "已兑换"][credit["status"].text] ?? "状态未知")
                    }.font(.caption)
                    if case .number(let timestamp) = credit["grantedAt"], timestamp.isFinite {
                        Text("发放：" + usageDateText(timestamp, includeTime: true)).font(.caption2).foregroundStyle(Design.secondary)
                    }
                    if case .number(let timestamp) = credit["expiresAt"], timestamp.isFinite {
                        Text("到期：" + usageDateText(timestamp, includeTime: true)).font(.caption2).foregroundStyle(Design.secondary)
                    }
                }
            }
            if let count = summary["availableCount"].int, count > summary["credits"].array.count {
                Text("部分卡片详情暂未提供").font(.caption2).foregroundStyle(Design.secondary)
            }
        }
    }
    private func redeem() async {
        guard confirmedEpoch == model.epoch, confirmedAccount == accountKey else {
            resetNotice = "工作区或账号已改变，请重新确认"; return
        }
        let version = model.epoch
        do {
            let outcome = try await model.redeemQuota(accountKey: confirmedAccount)
            guard model.epoch == version else { return }
            resetNotice = ["reset": "额度已重置", "alreadyRedeemed": "此请求已成功重置，未重复消耗", "nothingToReset": "当前没有可重置的额度，未消耗卡片", "noCredit": "当前没有可用重置卡"][outcome]
            await load(force: true)
        } catch {
            if model.epoch == version { resetNotice = error.localizedDescription }
        }
    }
    private func load(force: Bool = false) async {
        let version = UUID(), scope = model.scope
        requestVersion = version; failure = nil
        guard model.connected, model.device != nil else { loading = false; return }
        loading = true
        defer { if version == requestVersion { loading = false } }
        do {
            let result = try await model.cachedDeviceRequest("/api/usage", maxAge: force ? 0 : 30)
            guard !Task.isCancelled, scope == model.scope, version == requestVersion else { return }
            guard case .array = result["limits"] else { throw APIError("额度数据格式不正确") }
        } catch {
            if !Task.isCancelled, scope == model.scope, version == requestVersion {
                failure = (error as? APIError)?.status == 404 ? "本机服务尚不支持额度查询，请更新本机服务" : error.localizedDescription
            }
        }
    }
}

private struct CodexUsageWindow: View {
    @ScaledMetric(relativeTo: .caption) private var ringSize = 44.0
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
    private var tint: Color {
        guard let remaining else { return Design.secondary }
        if remaining >= 30 { return Design.green }
        if remaining >= 20 { return Design.orange }
        return Color(uiColor: .systemRed)
    }
    private var resetText: String? { usageResetText(window, includeTime: true) }
    private var ring: some View {
        ZStack {
            Circle().stroke(Design.secondary.opacity(0.15), lineWidth: 3)
            if let remaining {
                Circle().trim(from: 0, to: remaining / 100)
                    .stroke(tint, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                Text("\(remaining, specifier: "%.0f")%")
                    .font(.caption.weight(.medium)).monospacedDigit()
            } else {
                Text("—").font(.caption).foregroundStyle(Design.secondary)
            }
        }.frame(width: ringSize, height: ringSize)
    }
    var body: some View {
        Group {
            if compact {
                ring
            } else {
                HStack(spacing: 12) {
                    ring
                    VStack(alignment: .leading, spacing: 3) {
                        Text(label).font(.subheadline)
                        if let resetText { Text(resetText).font(.caption).foregroundStyle(Design.secondary) }
                    }
                    Spacer(minLength: 0)
                }
            }
        }.accessibilityElement(children: .ignore)
            .accessibilityLabel(label + (remaining.map { "，剩余 \(Int($0.rounded()))%" } ?? "，用量未知") + (resetText.map { "，" + $0 } ?? ""))
    }
}

private func usageResetText(_ window: JSONValue, includeTime: Bool = false) -> String? {
    guard case .number(let reset) = window["resetsAt"], reset.isFinite else { return nil }
    return usageDateText(reset, includeTime: includeTime) + "重置"
}

private func usageDateText(_ timestamp: Double, includeTime: Bool) -> String {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.timeZone = .current
    formatter.dateFormat = includeTime ? "yyyy-MM-dd HH:mm" : "yyyy-MM-dd"
    return formatter.string(from: Date(timeIntervalSince1970: timestamp))
}
