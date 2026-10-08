import Foundation
import Testing
@testable import CarryOnCore

struct ComposerDocumentTests {
    let skill = ComposerReference(name: "Review", path: "/fixture/review/SKILL.md")
    @Test func inlineIdentitySurvivesUnicodeEditsAndRestore() throws {
        var document = ComposerDocument(text: "检查 👋 ", skills: [skill])
        #expect(document.skills[0].offset == 6)
        #expect(document.displayText == "检查 👋 Review")
        document.replace(NSRange(location: 0, length: 0), with: "先")
        #expect(document.skills[0].offset == 7)
        #expect(document.wireText == "先检查 👋 ")
        let decoded = try JSONDecoder().decode([ComposerReference].self, from: JSONEncoder().encode(document.skills))
        #expect(ComposerDocument(text: document.text, skills: decoded) == document)
        #expect(decoded[0].value == skill.value)
    }
    @Test func displayNameSurvivesEditsAndRestoreWithoutChangingWireIdentity() throws {
        let reference = ComposerReference(name: "build-ios-apps", path: "/fixture/SKILL.md", displayName: "Build iOS Apps", iconData: "fixture-image")
        var document = ComposerDocument(text: "Use ", skills: [reference])
        document.replace(NSRange(location: 0, length: 0), with: "Please ")
        document.insert(.init(name: "other", path: "/other"), at: 0)
        document.remove(.init(name: "other", path: "/other"))
        let restored = try JSONDecoder().decode(ComposerDocumentSnapshot.self, from: JSONEncoder().encode(ComposerDocumentSnapshot(text: document.text, references: document.skills)))
        #expect(ComposerDocument(text: restored.text, skills: restored.references).displayText == "Please Use Build iOS Apps")
        #expect(restored.references[0].iconData == "fixture-image")
        #expect(restored.references[0].value == .object(["name": .string("build-ios-apps"), "path": .string("/fixture/SKILL.md")]))
    }
    private struct ComposerDocumentSnapshot: Codable { let text: String; let references: [ComposerReference] }
    @Test func deletingAttachmentRemovesIdentityAndShiftsRemaining() {
        var document = ComposerDocument(text: "", skills: [skill, .init(name: "Other", path: "/other")])
        document.replace(NSRange(location: 0, length: 1), with: "")
        #expect(document.skills.count == 1)
        #expect(document.skills[0].offset == 0)
        #expect(document.displayText == "Other")
        document.remove(document.skills[0])
        #expect(document.text.isEmpty && document.skills.isEmpty)
    }
    @Test func pastedObjectCharacterDoesNotForgeIdentity() {
        var document = ComposerDocument(text: "text", skills: [])
        document.replace(NSRange(location: 4, length: 0), with: "\u{fffc} external")
        #expect(document.skills.isEmpty)
        #expect(document.text == "text external")
    }
}
