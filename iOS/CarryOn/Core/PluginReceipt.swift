import Foundation

public struct PluginReceipt: Sendable {
    public let threadID: String
    public let path: String
    public let body: JSONValue
    public let completed: Bool
    public init(_ job: JSONValue) throws {
        guard let thread = job["threadId"].string, !thread.isEmpty, let fields = job["body"].object,
              (Set(fields.keys) == ["action", "pluginId"] || Set(fields.keys) == ["action", "pluginId", "discovery"]), job["body"]["pluginId"].string?.isEmpty == false else { throw APIError("插件管理凭证身份无效") }
        if let discovery = fields["discovery"] {
            guard let context = discovery.object, Set(context.keys) == ["searchTerm", "scope", "cursor"],
                  discovery["searchTerm"].string?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false,
                  ["global", "workspace", "personal"].contains(discovery["scope"].text),
                  discovery["cursor"] == .null || discovery["cursor"].string?.isEmpty == false else { throw APIError("插件搜索凭证身份无效") }
        }
        let action = job["body"]["action"].text
        guard ["install", "uninstall"].contains(action), job["kind"].text == "plugin-" + action else { throw APIError("插件管理凭证内容无效") }
        threadID = thread; body = job["body"]; path = "/api/threads/" + ConsoleAddress.component(thread) + "/plugins"
        completed = job["state"].text == "completed" && job["result"]["threadId"].text == thread && job["result"]["pluginId"] == body["pluginId"] && job["result"]["installed"].bool == (action == "install")
    }
}
