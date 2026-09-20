import Foundation
import Testing
@testable import CarryOnCore

@Test func connectionEvidenceNeverTreatsCachedTaskAsOnline() {
    func message(_ network: Bool? = true, _ device: Bool? = true, _ connected: Bool = true,
                 _ bridge: Bool? = true, local: Bool = false, failure: String? = nil) -> String? {
        ConversationConnection.message(networkAvailable: network, deviceOnline: device, connected: connected,
            bridgeEnabled: bridge, hasHistory: true, localHistory: local, readFailure: failure)
    }
    #expect(message() == nil)
    #expect(message(false, false, false) == "手机网络不可用，恢复后自动连接")
    #expect(message(true, false, false) == "电脑工作区离线，恢复后自动连接")
    #expect(message(true, true, false)?.contains("已保存") == true)
    #expect(message(true, true, true, false) == "Codex 未连接或桥接已暂停")
    #expect(message(local: true, failure: "missing")?.contains("读取失败") == true)
    #expect(message(local: true) == "桌面 Codex 尚未加载此会话，暂时无法连接。请先在桌面 Codex 打开此会话；当前可查看历史。")
}

@Test func changesPreserveEveryRecordedEditWithoutInventingACombinedDiff() {
    let change: JSONValue = .object(["id":.string("edit"),"type":.string("fileChange"),"data":.object([
        "changes":.array([.object(["path":.string("a.swift"),"diff":.string("-old\n+new")]),
                          .object(["path":.string("b.swift"),"diff":.string("+b")])])])])
    let second = change.setting("id",.string("edit-2"))
    let history: JSONValue = .object(["timeline":.array([change,second]),"historyWindow":.object(["hasMore":.bool(true)])])
    let files = ConversationChanges.files(history)
    #expect(files.map(\.path) == ["a.swift", "b.swift"])
    #expect(files[0].entries.count == 2)
    #expect(files[0].entries[0]["data"]["changes"].array.count == 1)
    #expect(files[0].entries[0]["data"]["changes"].array[0]["diff"].text == "-old\n+new")
    #expect(history["historyWindow"]["hasMore"].bool == true)
    #expect(!ConversationChanges.hasChanges(.null))
    #expect(ConversationChanges.hasChanges(.object(["timeline":.array([
        .object(["type":.string("turnDiff"),"data":.object(["diff":.string("+summary")])])])])) )
}

@Test func notificationAnchorDoesNotJumpToAnUnrelatedNewerResult() {
    let tid = "11111111-1111-4111-8111-111111111111"
    let target = PushTarget(server:"https://example.com",deviceID:"mac",threadID:tid,eventID:"e",turnID:"old")!
    let history: JSONValue = .object(["thread":.object(["id":.string(tid)]),"timeline":.array([
        .object(["id":.string("old-answer"),"turnId":.string("old"),"type":.string("agentMessage")]),
        .object(["id":.string("new-answer"),"turnId":.string("new"),"type":.string("agentMessage")])])])
    #expect(target.anchor(in:history) == "old-answer")
    #expect(target.anchor(in:history.setting("thread",.object(["id":.string("different")]))) == nil)
    let absent = PushTarget(server:"https://example.com",deviceID:"mac",threadID:tid,eventID:"e",turnID:"missing")!
    #expect(absent.anchor(in:history) == nil)
}

@Test func workspaceReadinessRequiresPositiveEvidence() {
    #expect(WorkspaceReadiness.label(online:false,status:.null,standby:.null) == "工作区离线")
    #expect(WorkspaceReadiness.label(online:true,status:.null,standby:.null) == "Codex 连接待确认")
    let state: JSONValue = .object(["enabled":.bool(true),"remoteControl":.bool(false)])
    #expect(!WorkspaceReadiness.label(online:true,status:state,standby:.null).contains("防休眠已生效"))
    #expect(WorkspaceReadiness.label(online:true,status:state,standby:.object(["effective":.bool(true)])) == "远程查看可用，防休眠已生效")
}
