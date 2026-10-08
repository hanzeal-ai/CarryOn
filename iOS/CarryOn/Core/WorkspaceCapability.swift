import Foundation

/// Client projection of carryon/workspaces/workspace_access.py; the console remains authoritative.
public enum WorkspaceCapability: String, CaseIterable, Sendable {
    case view, create, send, stop, edit, files, approve, resetQuota

    public func isGranted(in permissions: JSONValue) -> Bool {
        let values = permissions.array.compactMap(\.string)
        return values.contains("view") && values.contains(rawValue)
    }

    public static func operation(_ action: String) -> Self? {
        switch action {
        case "interrupt", "goal-pause", "goal-clear", "voice-stop": .stop
        case "steer", "resume", "queue-add", "queue-resume", "review", "goal-set", "voice-start": .send
        case "edit", "compact", "settings", "queue-edit", "queue-delete", "queue-reorder", "clear-queue": .edit
        case "command-approval", "file-approval", "permissions-approval", "user-input", "mcp-response": .approve
        default: nil
        }
    }

    public static func request(path: String, body: JSONValue? = nil) -> Set<Self>? {
        let path = String(path.prefix { $0 != "?" && $0 != "#" })
        if path.hasSuffix("/voice") || path.hasSuffix("/voice/audio") { return [.send] }
        guard let body else { return path.contains("/images/") || path.contains("/artifacts/") || path.hasSuffix("/files/search") ? [.files] : [.view] }
        if path.hasSuffix("/streams") || path.contains("/streams/") || path.contains("/notifications/") { return [.view] }
        if path.hasSuffix("/plugins") { return [.edit] }
        if path.hasSuffix("/skills/config") { return [.edit] }
        if path.hasSuffix("/terminals") { return [.stop] }
        if path == "/api/sections" || path.hasPrefix("/api/sections/") { return [.edit] }
        if path == "/api/usage/reset" { return [.resetQuota] }
        if path.hasPrefix("/api/side-chats/") && path.hasSuffix("/close") { return [.stop] }
        if path.hasSuffix("/archive") || path.hasSuffix("/unarchive") || path.hasSuffix("/rename") || path.hasSuffix("/section") { return [.edit] }
        if path.hasSuffix("/session") { return [.send] }
        if path.hasSuffix("/threads") {
            let fields = Set(body["settings"].object?.keys.map { $0 } ?? [])
            return fields.subtracting(["model", "effort"]).isEmpty ? [.create] : [.create, .edit]
        }
        if path.hasSuffix("/fork") || path.hasSuffix("/side-chats") { return [.create] }
        if path.hasSuffix("/messages") || path.hasSuffix("/compose") { return body["files"].array.isEmpty ? [.send] : [.send, .files] }
        if path.hasSuffix("/acknowledge") { return [.send] }
        if path.hasSuffix("/operations"), let capability = operation(body["action"].text) { return body["files"].array.isEmpty ? [capability] : [capability, .files] }
        return nil
    }
}
