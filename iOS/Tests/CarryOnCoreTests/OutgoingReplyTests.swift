import Foundation
import Testing
@testable import CarryOnCore

private func replyPrompt(answer: String = "允许") throws -> String {
    let record: JSONValue = .array([.object(["questionItemId": .string("question-1"), "question": .string("继续审查？"), "answer": .string(answer)])])
    return "<send_user_message_question_reply>\n" + String(decoding: try record.encoded(), as: UTF8.self) + "\n</send_user_message_question_reply>"
}

@Test func pendingReplyDisplaysReadableAnswerWithoutChangingWire() throws {
    let wire = try replyPrompt()
    #expect(OutgoingMessageProjection.displayText(wire) == "继续审查？\n允许")
    #expect(wire.contains("questionItemId"))
    for ordinary in ["允许", "<send_user_message_question_reply>invalid</send_user_message_question_reply>", "prefix " + wire] {
        #expect(OutgoingMessageProjection.displayText(ordinary) == ordinary)
    }
}

@Test func reflectedReplyMatchesQuestionIdentityAndAnswer() throws {
    let item: JSONValue = .object(["prompt": .string(try replyPrompt()), "state": .string("completed")])
    func history(_ id: String, _ answer: JSONValue) -> JSONValue {
        .object(["timeline": .array([.object(["asyncQuestions": .array([.object(["id": .string(id), "answer": answer])])])])])
    }
    #expect(OutgoingMessageProjection.isReflected(item, in: history("question-1", .string("允许"))))
    #expect(!OutgoingMessageProjection.isReflected(item, in: history("question-2", .string("允许"))))
    #expect(!OutgoingMessageProjection.isReflected(item, in: history("question-1", .string("拒绝"))))
    #expect(!OutgoingMessageProjection.isReflected(item, in: history("question-1", .null)))
}

@Test func ordinaryMessagesRequireNativeIdentityAndRejectedSteeringRemainsVisible() {
    let item: JSONValue = .object(["prompt": .string("same text"), "clientMessageId": .string("message-1"), "state": .string("completed")])
    func history(_ id: String, _ status: String) -> JSONValue {
        .object(["timeline": .array([.object(["type": .string("steeringUserMessage"), "nativeId": .string(id), "text": .string("same text"), "status": .string(status)])])])
    }
    #expect(!OutgoingMessageProjection.isReflected(item, in: history("another-message", "accepted")))
    #expect(!OutgoingMessageProjection.isReflected(item, in: history("message-1", "rejected")))
    #expect(OutgoingMessageProjection.isReflected(item, in: history("message-1", "accepted")))
}
