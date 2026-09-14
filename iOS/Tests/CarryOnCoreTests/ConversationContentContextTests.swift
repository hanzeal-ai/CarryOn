import XCTest
@testable import CarryOnCore

final class ConversationContentContextTests: XCTestCase {
    func testSideResourcesKeepParentScope() {
        let side = ConversationContentContext(parentID: "parent")
        XCTAssertTrue(side.isReadOnly)
        XCTAssertEqual(side.resourcePath(threadID: "child", kind: "artifacts", id: "file"), "/api/side-chats/child/artifacts/file?parentId=parent")
        XCTAssertEqual(side.resourcePath(threadID: "child", kind: "images", id: "image"), "/api/side-chats/child/images/image?parentId=parent")
        let main = ConversationContentContext()
        XCTAssertFalse(main.isReadOnly)
        XCTAssertEqual(main.resourcePath(threadID: "main", kind: "images", id: "image"), "/api/threads/main/images/image")
    }
}
