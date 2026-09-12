import Foundation

/// Preserves native identifiers, structured approval decisions and unknown event data.
public enum JSONValue: Codable, Sendable, Equatable, Hashable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null

    public init(from decoder: Decoder) throws {
        let box = try decoder.singleValueContainer()
        if box.decodeNil() { self = .null }
        else if let value = try? box.decode(Bool.self) { self = .bool(value) }
        else if let value = try? box.decode(String.self) { self = .string(value) }
        else if let value = try? box.decode(Double.self) { self = .number(value) }
        else if let value = try? box.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try box.decode([String: JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var box = encoder.singleValueContainer()
        switch self {
        case .object(let value): try box.encode(value)
        case .array(let value): try box.encode(value)
        case .string(let value): try box.encode(value)
        case .number(let value): try box.encode(value)
        case .bool(let value): try box.encode(value)
        case .null: try box.encodeNil()
        }
    }
    public subscript(_ key: String) -> JSONValue { object?[key] ?? .null }
    public var object: [String: JSONValue]? { if case .object(let v) = self { v } else { nil } }
    public var array: [JSONValue] { if case .array(let v) = self { v } else { [] } }
    public var string: String? { if case .string(let v) = self { v } else { nil } }
    public var text: String { string ?? "" }
    public var bool: Bool? { if case .bool(let v) = self { v } else { nil } }
    public var int: Int? {
        if case .number(let v) = self, v.isFinite, v.rounded() == v, v >= Double(Int.min), v < Double(Int.max) { return Int(v) }
        return nil
    }
    public func encoded() throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(self)
    }
    public var formatted: String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return (try? String(decoding: encoder.encode(self), as: UTF8.self)) ?? ""
    }
    public func setting(_ key: String, _ value: JSONValue) -> JSONValue {
        var fields = object ?? [:]; fields[key] = value; return .object(fields)
    }
}

public struct APIError: LocalizedError, Sendable {
    public let status: Int
    public let message: String
    public var errorDescription: String? { message }
    public init(_ message: String, status: Int = 0) { self.message = message; self.status = status }
}

public struct Record: Identifiable, Hashable, Sendable {
    public let id: String
    public let value: JSONValue
    public init(_ value: JSONValue) throws {
        guard let id = value["id"].string, !id.isEmpty else { throw APIError("服务器记录缺少标识") }
        self.id = id; self.value = value
    }
    public var title: String { value["title"].string ?? value["name"].string ?? id }
}

public struct RecordPage: Sendable {
    public let records: [Record]
    public let total: Int
    public let nextOffset: Int
    public init(_ json: JSONValue, key: String) throws {
        guard case .array(let rows) = json[key], let total = json["total"].int,
              let next = json["nextOffset"].int, total >= 0, next >= 0 else {
            throw APIError("服务器分页数据格式不正确")
        }
        self.records = try rows.map(Record.init)
        guard Set(records.map(\.id)).count == records.count else { throw APIError("服务器返回重复记录") }
        self.total = total; self.nextOffset = next
    }
}
