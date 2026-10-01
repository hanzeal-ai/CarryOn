import XCTest
@testable import CarryOnCore

final class UnifiedDiffTests: XCTestCase {
    func testLineNumbersAcrossHunksAndFiles() {
        let rows = UnifiedDiff.lines("--- a/a\n+++ b/a\n@@ -4,2 +4,2 @@\n same\n-old\n+new\n@@ -20 +21 @@\n-x\n+y\ndiff --git a/b b/b\n+unlocated")
        XCTAssertEqual(rows[3].old, 4); XCTAssertEqual(rows[3].new, 4)
        XCTAssertEqual(rows[4].location, "L5"); XCTAssertEqual(rows[5].location, "R5")
        XCTAssertEqual(rows[7].location, "L20"); XCTAssertEqual(rows[8].location, "R21")
        XCTAssertNil(rows[10].location)
    }
    func testMalformedAndHeaderLookingContentNeverInventLocations() {
        XCTAssertNil(UnifiedDiff.lines("@@ - + @@\n+text")[1].location)
        XCTAssertNil(UnifiedDiff.lines("+fragment")[0].location)
        let rows = UnifiedDiff.lines("@@ -1,2 +1,2 @@\n--- text\n+++ text\n\\ No newline at end of file")
        XCTAssertEqual(rows[1].kind, .removed); XCTAssertEqual(rows[2].kind, .added)
        XCTAssertNil(rows[3].location)
    }
    func testBoundsEndBeforeNextFileHeaders() {
        let rows = UnifiedDiff.lines("@@ -1 +1 @@\n-old\n+new\n--- a/next\n+++ b/next")
        XCTAssertNil(rows[3].location); XCTAssertNil(rows[4].location)
        XCTAssertNil(UnifiedDiff.lines("@@ -1 +1\n+broken")[1].location)
        XCTAssertNil(UnifiedDiff.lines("@@ -9223372036854775807 +1 @@\n-overflow")[1].location)
    }
}
