import Foundation

public struct PushTarget: Equatable, Sendable {
    public let server: String
    public let deviceID: String
    public let threadID: String
    public let eventID: String

    public init?(server: String?, deviceID: String?, threadID: String?, eventID: String?) {
        guard let server, let address = try? ConsoleAddress(server),
              let deviceID, !deviceID.isEmpty, deviceID.count <= 100,
              let threadID, UUID(uuidString: threadID) != nil,
              let eventID, !eventID.isEmpty, eventID.count <= 128 else { return nil }
        self.server = address.base.absoluteString
        self.deviceID = deviceID; self.threadID = threadID; self.eventID = eventID
    }
}
