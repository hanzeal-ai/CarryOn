// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CarryOnCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "CarryOnCore", targets: ["CarryOnCore"])],
    targets: [
        .target(name: "CarryOnCore", path: "CarryOn/Core"),
        .testTarget(name: "CarryOnCoreTests", dependencies: ["CarryOnCore"], path: "Tests/CarryOnCoreTests")
    ]
)
