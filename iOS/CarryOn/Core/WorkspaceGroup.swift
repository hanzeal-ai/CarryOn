import Foundation

/// Groups presentation only. Record IDs still address every request, cache and approval.
public struct WorkspaceGroup: Identifiable, Sendable {
    public let id: String
    public let title: String
    public var connections: [Record]

    public static func groups(_ devices: [Record]) -> [WorkspaceGroup] {
        var result: [WorkspaceGroup] = []
        for device in devices {
            let workspace = device.value["workspace"]
            let identity = workspace["id"].string.flatMap { $0.isEmpty ? nil : $0 }
            let key = identity.map { "workspace:" + $0 } ?? "connection:" + device.id
            if let index = result.firstIndex(where: { $0.id == key }) {
                result[index].connections.append(device)
            } else {
                result.append(WorkspaceGroup(id: key, title: identity == nil ? device.title : (workspace["name"].string ?? device.title), connections: [device]))
            }
        }
        return result
    }

    public static func connectionLabel(_ device: Record) -> String {
        switch device.value["workspace"]["backend"].text {
        case "desktop-ipc": return "桌面端"
        case "codex-cli": return "CLI"
        case "app-server": return "独立环境"
        default: return device.title
        }
    }
}
