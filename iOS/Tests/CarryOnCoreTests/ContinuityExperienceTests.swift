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

@Test func changeCountsExcludePatchHeadersAndKeepHeaderLikeContent() {
    let diff = """
    diff --git a/a.swift b/a.swift
    --- a/a.swift
    +++ b/a.swift
    @@ -1,2 +1,3 @@
    -old
    --- removed content
    +new
    +++ added content
    +another
    """
    #expect(ConversationChanges.lineCounts(diff) == .init(added: 3, removed: 2))
    #expect(ConversationChanges.lineCounts("-old\n+new") == .init(added: 1, removed: 1))
    #expect(ConversationChanges.lineCounts("") == nil)
    #expect(ConversationChanges.lineCounts("Binary files differ") == nil)
    #expect(ConversationChanges.lineCounts("--- a/file\n+++ b/file") == nil)
}

@Test func fileChangeCountsAccumulateRecordedEditsAndDoNotInventMissingStats() {
    func edit(_ path: String, _ diff: String, status: String = "completed") -> JSONValue {
        .object(["type": .string("fileChange"), "status": .string(status), "data": .object([
            "changes": .array([.object(["path": .string(path), "diff": .string(diff)])])])])
    }
    let history: JSONValue = .object(["timeline": .array([
        edit("a.swift", "-old\n+first"), edit("a.swift", "-first\n+second\n+third"),
        edit("b.png", "Binary files differ"), edit("c.swift", "+never applied", status: "failed"),
        .object(["type": .string("turnDiff"), "data": .object(["diff": .string("+summary")])])])])
    let files = ConversationChanges.files(history)
    #expect(files.count == 3)
    #expect(files[0].lineCounts == .init(added: 3, removed: 2))
    #expect(files[1].lineCounts == nil)
    #expect(files[2].lineCounts == nil)
}

@Test func changeCardsBelongToTheirOwnTurnAndFollowItsLastMessage() {
    func item(_ id: String, _ turn: String, _ type: String, paths: [String] = []) -> JSONValue {
        .object(["id": .string(id), "turnId": .string(turn), "type": .string(type), "data": .object([
            "changes": .array(paths.map { .object(["path": .string($0), "diff": .string("+new")]) })])])
    }
    let source = [item("t1", "one", "turn").setting("status", .string("completed")),
        item("u1", "one", "userMessage"),
        item("e1", "one", "fileChange", paths: ["shared.swift", "old.swift"]),
        item("a1", "one", "agentMessage"),
        item("t2", "two", "turn").setting("status", .string("completed")),
        item("u2", "two", "userMessage"),
        item("e2", "two", "fileChange", paths: ["shared.swift", "b", "c", "d"]),
        item("e3", "two", "fileChange", paths: ["shared.swift"]),
        item("a2", "two", "agentMessage"), item("u3", "three", "userMessage"),
        item("a3", "three", "agentMessage"), item("unknown", "", "fileChange", paths: ["unattributed"])]
    let rows = ConversationChanges.timeline(ConversationProcess.timeline(source), source: source)
    let cards = rows.filter { $0["type"].text == "changesSummary" }
    #expect(cards.count == 2)
    let first = ConversationChanges.Snapshot(cards[0]["history"])
    let second = ConversationChanges.Snapshot(cards[1]["history"])
    #expect(first.files.map(\.path) == ["shared.swift", "old.swift"])
    #expect(second.files.map(\.path) == ["shared.swift", "b", "c", "d"])
    #expect(second.files[0].entries.count == 2)
    #expect(first.totals == .init(added: 2, removed: 0))
    #expect(second.totals == .init(added: 5, removed: 0))
    for card in cards {
        let index = rows.firstIndex(of: card)!
        #expect(rows[index - 1]["id"].text == (card["turnId"].text == "one" ? "a1" : "a2"))
    }
    // Even completed file edits and a final answer cannot complete a running turn.
    for status in ["inProgress", "failed", "interrupted", "", "unknown"] {
        let pending = source.map { $0["id"].text == "t2" ? $0.setting("status", .string(status)) : $0 }
        let pendingCards = ConversationChanges.timeline(ConversationProcess.timeline(pending), source: pending)
            .filter { $0["type"].text == "changesSummary" }
        #expect(pendingCards.map { $0["turnId"].text } == ["one"])
    }
    let missingStatus = source.filter { $0["id"].text != "t2" }
    #expect(ConversationChanges.timeline(ConversationProcess.timeline(missingStatus), source: missingStatus)
        .filter { $0["type"].text == "changesSummary" }.count == 1)
    #expect(ConversationChanges.timeline([], source: []).isEmpty)
}
