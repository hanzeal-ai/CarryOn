import XCTest
@testable import CarryOnCore

final class WorkspaceGroupTests: XCTestCase {
    private func device(_ id: String, group: String? = "shared", backend: String = "desktop-ipc") throws -> Record {
        try Record(.object(["id": .string(id), "name": .string("设备"), "workspace": group.map { .object(["id": .string($0), "name": .string("电脑"), "backend": .string(backend)]) } ?? .null]))
    }
    func testConnectionsKeepTheirIdentitiesInsideOneWorkspace() throws {
        let desktop = try device("desktop"), cli = try device("cli", backend: "codex-cli")
        let groups = WorkspaceGroup.groups([desktop, cli, try device("independent", group: "other")])
        XCTAssertEqual(groups.count, 2)
        XCTAssertEqual(groups[0].title, "电脑")
        XCTAssertEqual(groups[0].connections.map(\.id), ["desktop", "cli"])
        XCTAssertEqual(WorkspaceGroup.connectionLabel(desktop), "桌面端")
        XCTAssertEqual(WorkspaceGroup.connectionLabel(cli), "CLI")
    }
    func testLegacyEntriesWithSameNameNeverMerge() throws {
        XCTAssertEqual(WorkspaceGroup.groups([try device("a", group: nil), try device("b", group: nil)]).count, 2)
        XCTAssertEqual(WorkspaceGroup.groups([try device("a", group: ""), try device("b", group: "")]).count, 2)
    }
    func testRemovingOneConnectionPreservesOtherAndGroup() throws {
        let a = try device("a"), b = try device("b", backend: "codex-cli")
        let before = WorkspaceGroup.groups([a, b]), after = WorkspaceGroup.groups([b])
        XCTAssertEqual(before[0].id, after[0].id)
        XCTAssertEqual(after[0].connections.map(\.id), ["b"])
    }
}
