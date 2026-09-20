import Foundation

/// Connection evidence is independent of the native task's execution state.
public enum ConversationConnection {
    public static func message(networkAvailable: Bool?, deviceOnline: Bool?, connected: Bool,
                               bridgeEnabled: Bool?, hasHistory: Bool, localHistory: Bool,
                               readFailure: String?) -> String? {
        if networkAvailable == false { return "手机网络不可用，恢复后自动连接" }
        if deviceOnline == false { return "电脑工作区离线，恢复后自动连接" }
        if !connected { return hasHistory ? "连接正在恢复，当前显示已保存的记录" : "正在连接工作区…" }
        if bridgeEnabled == false { return "Codex 未连接或桥接已暂停" }
        if readFailure != nil { return "历史读取失败，当前任务状态待确认" }
        if localHistory { return "桌面 Codex 尚未加载此会话，暂时无法连接。请先在桌面 Codex 打开此会话；当前可查看历史。" }
        return nil
    }
}
