import Foundation
import CarryOnCore

extension AppModel {
    func hasPendingQuotaReset(accountKey: String) -> Bool {
        pending.hasPending(scope: scope, target: "quota:" + accountKey)
    }
    func redeemQuota(accountKey: String) async throws -> String {
        guard canWrite(.resetQuota), !accountKey.isEmpty else { throw APIError("当前工作区未连接或未授权使用重置卡") }
        let version = epoch, capturedScope = scope, target = "quota:" + accountKey
        let path = "/api/usage/reset"
        let body: JSONValue = .object(["accountKey": .string(accountKey), "confirmed": .bool(true)])
        writing = true
        defer { writing = false }
        let identifier = try pending.requestID(scope: capturedScope, target: target, path: path, body: body)
        let result = try await deviceRequest(path, body: body.setting("requestId", .string(identifier)))
        guard epoch == version, scope == capturedScope else { throw CancellationError() }
        if result["state"].text == "failed" {
            try pending.resolve(scope: capturedScope, target: target, requestID: identifier)
            throw APIError(result["error"].string ?? "重置未发送，请刷新后重试")
        }
        let outcome = result["result"]["outcome"].text
        guard result["state"].text == "completed", ["reset", "alreadyRedeemed", "nothingToReset", "noCredit"].contains(outcome) else {
            throw APIError("重置结果尚未确认，请使用原请求核对并重试；不要在其他设备发起新的重置")
        }
        try pending.resolve(scope: capturedScope, target: target, requestID: identifier)
        return outcome
    }
}
