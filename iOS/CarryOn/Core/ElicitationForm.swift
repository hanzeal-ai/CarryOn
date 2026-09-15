import Foundation

public enum ElicitationForm {
    /// Handle flat primitive forms; unfamiliar schemas remain in the native client.
    public static func supports(_ schema: JSONValue) -> Bool {
        if schema == .null { return true }
        guard schema["type"].text == "object", schema["properties"].object != nil else { return false }
        let rootKeys: Set<String> = ["type", "properties", "required", "title", "description", "additionalProperties", "$schema"]
        guard Set(schema.object?.keys.map { $0 } ?? []).isSubset(of: rootKeys) else { return false }
        let fieldKeys: Set<String> = ["type", "title", "description", "enum", "enumNames", "default", "minLength", "maxLength", "minimum", "maximum"]
        let properties = schema["properties"].object!
        if schema["required"] != .null {
            guard case .array(let required) = schema["required"], required.allSatisfy({ $0.string.map { properties[$0] != nil } == true }) else { return false }
        }
        if schema["additionalProperties"] != .null && schema["additionalProperties"].bool == nil { return false }
        return properties.values.allSatisfy { field in
            guard ["string", "number", "integer", "boolean"].contains(field["type"].text),
                Set(field.object?.keys.map { $0 } ?? []).isSubset(of: fieldKeys) else { return false }
            for key in ["minimum", "maximum"] where field[key] != .null {
                guard case .number(let number) = field[key], number.isFinite else { return false }
            }
            for key in ["minLength", "maxLength"] where field[key] != .null {
                guard case .number(let number) = field[key], number.isFinite, number >= 0, number.rounded() == number else { return false }
            }
            if field["enum"] != .null {
                guard case .array(let options) = field["enum"], !options.isEmpty,
                    options.allSatisfy({ valid($0, field: field) }) else { return false }
            }
            return true
        }
    }
    private static func valid(_ value: JSONValue, field: JSONValue) -> Bool {
        switch (field["type"].text, value) {
        case ("string", .string(let text)):
            let count = text.unicodeScalars.count
            return (field["minLength"].int.map { count >= $0 } ?? true) && (field["maxLength"].int.map { count <= $0 } ?? true)
        case ("number", .number(let number)), ("integer", .number(let number)):
            guard number.isFinite, field["type"].text != "integer" || number.rounded() == number else { return false }
            if case .number(let minimum) = field["minimum"], number < minimum { return false }
            if case .number(let maximum) = field["maximum"], number > maximum { return false }
            return true
        case ("boolean", .bool): return true
        default: return false
        }
    }

    public static func response(_ schema: JSONValue, values: [String: String]) throws -> JSONValue {
        guard supports(schema) else { throw APIError("请在 Codex App 完成此请求") }
        if schema == .null { return .null }
        var content: [String: JSONValue] = [:]
        for (key, field) in schema["properties"].object ?? [:] {
            let raw = values[key] ?? "", title = field["title"].string ?? key
            if raw.isEmpty {
                if schema["required"].array.contains(.string(key)) { throw APIError("请填写：" + title) }
                continue
            }
            let value: JSONValue
            if !field["enum"].array.isEmpty {
                guard let option = field["enum"].array.first(where: { $0.formatted == raw }) else { throw APIError("请选择：" + title) }
                value = option
            } else if field["type"].text == "boolean" {
                guard ["true", "false"].contains(raw) else { throw APIError("请选择：" + title) }
                value = .bool(raw == "true")
            } else if ["number", "integer"].contains(field["type"].text) {
                guard let number = Double(raw), number.isFinite, field["type"].text != "integer" || number.rounded() == number else { throw APIError("数字格式不正确：" + title) }
                if case .number(let min) = field["minimum"], number < min { throw APIError(title + "低于最小值") }
                if case .number(let max) = field["maximum"], number > max { throw APIError(title + "超过最大值") }
                value = .number(number)
            } else {
                if let min = field["minLength"].int, raw.unicodeScalars.count < min { throw APIError(title + "内容过短") }
                if let max = field["maxLength"].int, raw.unicodeScalars.count > max { throw APIError(title + "内容过长") }
                value = .string(raw)
            }
            guard valid(value, field: field) else { throw APIError("内容不符合要求：" + title) }
            content[key] = value
        }
        return .object(content)
    }
}
