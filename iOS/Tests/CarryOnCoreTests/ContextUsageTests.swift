import Testing
@testable import CarryOnCore

@Test func nativeContextUsageRequiresRealCounters() {
    #expect(ContextUsage(.null) == nil)
    #expect(ContextUsage(.object(["modelContextWindow": .number(0), "last": .object(["totalTokens": .number(5)])])) == nil)
    #expect(ContextUsage(.object(["modelContextWindow": .number(1000), "last": .object(["totalTokens": .number(-1)])])) == nil)
    #expect(ContextUsage(.object(["modelContextWindow": .number(1000), "total": .object(["totalTokens": .number(500)])])) == nil)
    let normal = ContextUsage(.object(["modelContextWindow": .number(1000), "last": .object(["totalTokens": .number(250)])]))
    #expect(normal?.percentage == 25)
    #expect(normal?.remaining == 750)
    let exceeded = ContextUsage(.object(["modelContextWindow": .number(1000), "last": .object(["totalTokens": .number(1200)])]))
    #expect(exceeded?.used == 1200)
    #expect(exceeded?.percentage == 100)
    #expect(exceeded?.remaining == 0)
}
