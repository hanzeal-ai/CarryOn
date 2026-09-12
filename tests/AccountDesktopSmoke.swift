import Foundation

@main struct AccountDesktopSmoke {
    @MainActor static func main() async throws {
        let values = ProcessInfo.processInfo.environment
        let url = values["CARRYON_TEST_ACCOUNT_URL"]!
        let token = values["CARRYON_TEST_SETUP_TOKEN"]!
        let model = SettingsModel()
        precondition(CloudAccountView.consoleURL("wss://example.test/carryon/device") == "https://example.test/carryon")
        let status = await model.call(["cloud", "account", "status", "--url", url])
        precondition(status.code == 0 && model.object(status.text)?["configured"] as? Bool == false, status.text)
        let setup = await model.configureAccount(url: url, action: "setup", fields: [
            "setupToken": token, "username": "desktop-owner", "password": "desktop-test-password-123"
        ])
        precondition(setup.code == 0, setup.text)
        precondition(!setup.text.contains(token) && !setup.text.contains("desktop-test-password-123"))
        let wrong = await model.configureAccount(url: url, action: "change", fields: [
            "currentUsername": "desktop-owner", "currentPassword": "wrong", "username": "new-owner", "password": "new-desktop-test-password"
        ])
        precondition(wrong.code != 0)
        let change = await model.configureAccount(url: url, action: "change", fields: [
            "currentUsername": "desktop-owner", "currentPassword": "desktop-test-password-123", "username": "new-owner", "password": "new-desktop-test-password"
        ])
        precondition(change.code == 0, change.text)
        let after = await model.call(["cloud", "account", "status", "--url", url])
        precondition(after.code == 0 && model.object(after.text)?["configured"] as? Bool == true, after.text)
        let qr = await model.qrRequest(url: url, fields: ["action": "create", "username": "new-owner", "password": "new-desktop-test-password"])
        precondition(qr.code == 0, qr.text)
        let invitation = model.object(qr.text)!
        let fields = ["id": invitation["id"] as! String, "session": invitation["session"] as! String]
        let waiting = await model.qrRequest(url: url, fields: fields.merging(["action": "status"]) { _, new in new })
        precondition(waiting.code == 0 && model.object(waiting.text)?["state"] as? String == "waiting", waiting.text)
        let closed = await model.qrRequest(url: url, fields: fields.merging(["action": "close"]) { _, new in new })
        precondition(closed.code == 0, closed.text)
        print("Desktop QR create/status/close passed")
        print("Desktop model → CLI stdin → HTTPS setup/change passed")
    }
}
