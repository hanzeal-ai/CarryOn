import Foundation

public enum WorkspaceReadiness {
    public static func label(online: Bool?, status: JSONValue, standby: JSONValue) -> String {
        if online == false { return "工作区离线" }
        guard online == true else { return "连接状态待确认" }
        if status["enabled"].bool == false { return "Codex 未连接或桥接已暂停" }
        guard status["enabled"].bool == true else { return "Codex 连接待确认" }
        if standby["effective"].bool == false { return "可以远程查看，电脑休眠后可能断开" }
        guard standby["effective"].bool == true else { return "可以远程查看，待机状态待确认" }
        return status["remoteControl"].bool == true ? "远程查看与操作可用，防休眠已生效" : "远程查看可用，防休眠已生效"
    }
}
