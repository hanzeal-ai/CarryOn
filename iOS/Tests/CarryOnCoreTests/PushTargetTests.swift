import Testing
@testable import CarryOnCore

@Test func pushTargetRequiresAnHTTPSConsoleAndValidThread() {
    let tid = "11111111-1111-4111-8111-111111111111"
    let target = PushTarget(server: "https://example.com/base", deviceID: "mac", threadID: tid, eventID: "event1")
    #expect(target?.server == "https://example.com/base/")
    #expect(target?.threadID == tid)
    #expect(PushTarget(server: "http://example.com", deviceID: "mac", threadID: tid, eventID: "event1") == nil)
    #expect(PushTarget(server: "https://example.com", deviceID: "mac", threadID: "../../other", eventID: "event1") == nil)
}
