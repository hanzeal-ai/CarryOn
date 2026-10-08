import Foundation

public struct SkillConfigurationReceipt: Sendable {
    public let threadID: String
    public let path: String
    public let body: JSONValue
    public let completed: Bool
    public init(_ job: JSONValue) throws {
        guard job["kind"].text == "skill-config", let thread = job["threadId"].string, !thread.isEmpty,
              let fields = job["body"].object, Set(fields.keys) == ["path", "enabled"],
              job["body"]["path"].string?.isEmpty == false, job["body"]["enabled"].bool != nil else { throw APIError("技能配置凭证身份无效") }
        threadID = thread; body = job["body"]; path = "/api/threads/" + ConsoleAddress.component(thread) + "/skills/config"
        completed = job["state"].text == "completed" && job["result"]["threadId"].text == thread && job["result"]["path"] == body["path"] && job["result"]["enabled"] == body["enabled"]
    }
}
