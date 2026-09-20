import Foundation

public struct PushTarget: Equatable, Sendable {
    public let server: String
    public let deviceID: String
    public let threadID: String
    public let eventID: String
    public let turnID: String?
    public let itemID: String?
    public let requestID: String?

    public init?(server: String?, deviceID: String?, threadID: String?, eventID: String?, turnID: String? = nil, itemID: String? = nil, requestID: String? = nil) {
        guard let server, let address = try? ConsoleAddress(server),
              let deviceID, !deviceID.isEmpty, deviceID.count <= 100,
              let threadID, UUID(uuidString: threadID) != nil,
              let eventID, !eventID.isEmpty, eventID.count <= 128 else { return nil }
        self.server = address.base.absoluteString
        func bounded(_ value: String?) -> String? {
            guard let value, !value.isEmpty, value.count <= 200 else { return nil }
            return value
        }
        self.turnID = bounded(turnID); self.itemID = bounded(itemID); self.requestID = bounded(requestID)
        self.deviceID = deviceID; self.threadID = threadID; self.eventID = eventID
    }
    public var hasAnchor: Bool { turnID != nil || itemID != nil || requestID != nil }
    public func anchor(in history: JSONValue) -> String? {
        guard history["thread"]["id"].text == threadID else { return nil }
        let timeline = history["timeline"].array
        if let itemID, let item = timeline.first(where: { $0["nativeId"].text == itemID || $0["id"].text == itemID }) { return item["id"].string }
        if let requestID, history["controls"]["requests"].array.contains(where: { $0["id"].text == requestID }) {
            return ActivityDetail(history: history).anchorID
        }
        if let turnID {
            let items = timeline.filter { $0["turnId"].text == turnID }
            return items.last(where: { $0["type"].text == "error" })?["id"].string
                ?? items.last(where: { $0["type"].text == "agentMessage" && !["analysis", "commentary"].contains($0["phase"].text) })?["id"].string
                ?? ConversationProcess.timeline(items).last?["id"].string
        }
        return hasAnchor ? nil : ActivityDetail(history: history).anchorID
    }
}
