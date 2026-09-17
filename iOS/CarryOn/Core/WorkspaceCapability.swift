import Foundation

/// Client projection of carryon/workspace_access.py; the console remains authoritative.
public enum WorkspaceCapability: String, CaseIterable, Sendable {
    case view, create, send, stop, edit, files, approve

    public func isGranted(in permissions: JSONValue) -> Bool {
        let values = permissions.array.compactMap(\.string)
        return values.contains("view") && values.contains(rawValue)
    }

    public static func operation(_ action: String) -> Self? {
        switch action {
        case "interrupt": .stop
        case "steer", "resume", "queue-add", "queue-resume": .send
        case "edit", "compact", "settings", "queue-edit", "queue-delete", "queue-reorder", "clear-queue": .edit
        case "command-approval", "file-approval", "permissions-approval", "user-input", "mcp-response": .approve
        default: nil
        }
    }

    public static func request(path: String, body: JSONValue? = nil) -> Self? {
        let path = String(path.prefix { $0 != "?" && $0 != "#" })
        guard let body else { return path.contains("/images/") || path.contains("/artifacts/") ? .files : .view }
        if path.hasSuffix("/streams") || path.contains("/streams/") || path.contains("/notifications/") { return .view }
        if path.hasSuffix("/threads") { return .create }
        if path.hasSuffix("/messages") || path.hasSuffix("/compose") || path.hasSuffix("/acknowledge") { return .send }
        if path.hasSuffix("/operations") { return operation(body["action"].text) }
        return nil
    }
}
