import CarryOnCore

/// Display metadata never replaces the model ID sent to the native runtime.
enum ModelPresentation {
    static func name(_ id: String, catalog: JSONValue) -> String {
        let label = catalog["models"].array.first { $0["id"].text == id }?["name"].string ?? id
        return label.prefix(4).lowercased() == "gpt-" ? String(label.dropFirst(4)) : label
    }
    static func effort(_ value: String) -> String {
        switch value {
        case "none": "无"
        case "minimal": "最少"
        case "low": "低"
        case "medium": "中"
        case "high": "高"
        case "xhigh": "超高"
        case "max": "最高"
        case "ultra": "极高"
        default: value.prefix(1).uppercased() + value.dropFirst()
        }
    }
}
