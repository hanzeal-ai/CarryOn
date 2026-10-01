import CarryOnCore

/// Display metadata never replaces the model ID sent to the native runtime.
enum ModelPresentation {
    static func name(_ id: String, catalog: JSONValue) -> String {
        catalog["models"].array.first { $0["id"].text == id }?["name"].string ?? id
    }
    static func effort(_ value: String) -> String {
        value.prefix(1).uppercased() + value.dropFirst()
    }
}
