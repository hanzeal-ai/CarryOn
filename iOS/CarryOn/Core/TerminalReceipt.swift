import Foundation

public struct TerminalReceipt: Sendable {
    public let threadID: String
    public let path: String
    public let body: JSONValue
    public let completed: Bool
    public init(_ job: JSONValue) throws {
        guard let thread = job["threadId"].string, !thread.isEmpty, let fields = job["body"].object else { throw APIError("终端凭证身份无效") }
        threadID = thread; body = job["body"]; path = "/api/threads/" + ConsoleAddress.component(thread) + "/terminals"
        let action = body["action"].text
        guard ["terminate", "clean"].contains(action), job["kind"].text == "terminal-" + action,
              Set(fields.keys) == (action == "clean" ? ["action"] : ["action", "processId"]),
              action != "terminate" || body["processId"].string?.isEmpty == false else { throw APIError("终端凭证内容无效") }
        completed = job["state"].text == "completed" && job["result"]["threadId"].text == thread && (action == "clean" ? job["result"]["cleaned"].bool == true : job["result"]["terminated"].bool == true && job["result"]["processId"] == body["processId"])
    }
}
