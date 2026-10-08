"""Use a private UIKit pasteboard in owned copies, avoiding host clipboard sync."""
from pathlib import Path

for file in (source / "CarryOn").rglob("*.swift"):
    text = file.read_text()
    if "UIPasteboard.general" in text:
        file.write_text(text.replace("UIPasteboard.general", "FixtureClipboard.board"))
app = source / "CarryOn/App/CarryOnApp.swift"
with app.open("a") as handle:
    handle.write('''
@MainActor enum FixtureClipboard {
    static let board = UIPasteboard(name: .init("com.hanzeal.carryon.owned-fixture." + UUID().uuidString), create: true)!
}
''')
