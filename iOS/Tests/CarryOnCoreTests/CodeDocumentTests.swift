import XCTest
@testable import CarryOnCore

final class CodeDocumentTests: XCTestCase {
    func testFileTypesAndBinaryFallback() {
        XCTAssertEqual(CodeDocument.language(filename: "/tmp/App.SWIFT"), "swift")
        XCTAssertEqual(CodeDocument.language(filename: "Dockerfile"), "dockerfile")
        XCTAssertEqual(CodeDocument.language(filename: "component.tsx"), "typescript")
        XCTAssertNil(CodeDocument(name: "image.png", data: Data("text".utf8)))
        XCTAssertNil(CodeDocument(name: "code.swift", data: Data([0xff, 0xfe])))
        XCTAssertNil(CodeDocument(name: "code.swift", data: Data([65, 0, 66])))
        XCTAssertEqual(CodeDocument(name: "readme.md", data: Data("# 标题".utf8))?.isMarkdown, true)
    }
    func testFenceLanguageAndUnknownLanguage() {
        XCTAssertEqual(CodeDocument.normalizedLanguage("TS linenums"), "typescript")
        XCTAssertEqual(CodeDocument.normalizedLanguage(nil), "plaintext")
        XCTAssertEqual(CodeDocument.normalizedLanguage("newlang"), "newlang")
    }
}
