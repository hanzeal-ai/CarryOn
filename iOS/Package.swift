// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ConnectNowCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "ConnectNowCore", targets: ["ConnectNowCore"])],
    targets: [
        .target(name: "ConnectNowCore", path: "ConnectNow/Core"),
        .testTarget(name: "ConnectNowCoreTests", dependencies: ["ConnectNowCore"], path: "Tests/ConnectNowCoreTests")
    ]
)
