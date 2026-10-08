import Foundation

/// A native section receipt identifies the exact submitted body before releasing a write.
public struct SectionReceipt: Sendable {
    public let path: String
    public let body: JSONValue
    public let completed: Bool
    public init(_ job: JSONValue) throws {
        let kind = job["kind"].text
        guard ["section-create", "section-update", "section-delete", "section-order"].contains(kind),
              let fields = job["body"].object, job.object?.keys.contains("sectionId") == true else { throw APIError("分组管理凭证无效") }
        body = job["body"]
        let sectionID = job["sectionId"].string
        if kind == "section-create" {
            guard job["sectionId"] == .null, job["threadId"].text == "sections", Set(fields.keys) == ["name"], let name = body["name"].string, !name.isEmpty else { throw APIError("分组创建凭证不匹配") }
            path = "/api/sections"
        } else if kind == "section-order" {
            guard let sectionID, !sectionID.isEmpty, Set(fields.keys) == ["action", "threadId", "beforeThreadId"],
                  body["action"].text == "order", body["threadId"].string?.isEmpty == false, job["threadId"] == body["threadId"],
                  body["beforeThreadId"] == .null || body["beforeThreadId"].string?.isEmpty == false else { throw APIError("分组顺序凭证不匹配") }
            path = "/api/sections/" + ConsoleAddress.component(sectionID)
        } else {
            let action = kind == "section-update" ? "update" : "delete"
            guard let sectionID, !sectionID.isEmpty, job["threadId"].text == sectionID,
                  body["action"].text == action, Set(fields.keys) == (action == "update" ? ["action", "name"] : ["action"]),
                  action != "update" || body["name"].string?.isEmpty == false else { throw APIError("分组管理内容不匹配") }
            path = "/api/sections/" + ConsoleAddress.component(sectionID)
        }
        if job["state"].text != "completed" { completed = false }
        else if kind == "section-order" { completed = job["result"]["threadId"] == body["threadId"] && job["result"]["sectionId"].string == sectionID && job["result"].object?.keys.contains("beforeThreadId") == true && job["result"]["beforeThreadId"] == body["beforeThreadId"] }
        else if kind == "section-delete" { completed = job["result"]["sectionId"].string == sectionID && job["result"]["deleted"].bool == true }
        else {
            let section = job["result"]["section"]
            completed = section["id"].string?.isEmpty == false && section["name"] == body["name"] && (kind == "section-create" || section["id"].string == sectionID)
        }
    }
}
