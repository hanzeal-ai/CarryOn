import Foundation
import Testing
@testable import CarryOnCore

@Test func backgroundUncertaintyIsLoggedWithoutAlertButWriteStillBlocks() {
    var log = RuntimeLog()
    let failure = APIError("设备响应未确认；使用原 requestId 查询，不要自动重发", status: 409)
    let time = Date(timeIntervalSince1970: 123)
    let alert1 = log.record(failure, operation: "刷新动态", workspace: "Mac", blocking: false, date: time)
    #expect(!alert1)
    #expect(log.entries.first?.date == time)
    #expect(log.entries.first?.message == failure.localizedDescription)
    #expect(log.entries.first?.operation == "刷新动态")
    #expect(log.entries.first?.workspace == "Mac")
    let alert2 = log.record(failure, operation: "发送消息", workspace: "Mac", blocking: true)
    #expect(alert2)
    #expect(log.entries.first?.blocking == true)
}

@Test func backgroundAuthenticationExpiryNeedsActionAndCancellationIsSilent() {
    var log = RuntimeLog()
    let alert3 = log.record(APIError("登录已失效", status: 401), operation: "刷新动态", workspace: "", blocking: false)
    #expect(alert3)
    let alert4 = log.record(CancellationError(), operation: "切换工作区", workspace: "", blocking: true)
    #expect(!alert4)
    let alert5 = log.record(URLError(.cancelled), operation: "取消订阅", workspace: "", blocking: true)
    #expect(!alert5)
    #expect(log.entries.count == 1)
}

@Test func runtimeLogRetainsNewestTwoHundredIssues() {
    var log = RuntimeLog()
    for i in 0..<205 {
        log.record(URLError(.timedOut), operation: "刷新 \(i)", workspace: "Mac", blocking: false)
    }
    #expect(log.entries.count == 200)
    #expect(log.entries.first?.operation == "刷新 204")
    #expect(log.entries.last?.operation == "刷新 5")
}
