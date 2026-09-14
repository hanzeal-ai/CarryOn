import SwiftUI
import VisionKit
import AVFoundation
import CarryOnCore

struct QRLoginView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var camera = false
    @State private var code: LoginCode?
    @State private var verification: String?
    @State private var failure: String?
    @State private var confirmed = false
    var body: some View {
        NavigationStack {
            VStack(spacing: 22) {
                if let code {
                    Image(systemName: "laptopcomputer").font(.system(size: 44))
                    Text(code.address.base.absoluteString).font(.headline).textSelection(.enabled)
                    if let verification {
                        Text(verification).font(.system(size: 36, weight: .semibold, design: .monospaced))
                        Text("在电脑上核对确认码，并允许本次登录。").foregroundStyle(Design.secondary)
                        if failure == nil { ProgressView() }
                    } else {
                        Text("确认登录此云端地址").foregroundStyle(Design.secondary)
                        Button("继续登录") { confirmed = true }.buttonStyle(.borderedProminent).disabled(confirmed)
                    }
                } else if camera {
                    QRScanner(onScan: { raw in
                        do { code = try LoginCode(raw); camera = false }
                        catch { failure = error.localizedDescription; camera = false }
                    }, onFailure: { failure = "相机暂不可用，请稍后重试。"; camera = false }).clipShape(RoundedRectangle(cornerRadius: 16))
                    Text("扫描电脑控制台「扫码登录其他设备」中的二维码。").font(.callout).foregroundStyle(Design.secondary)
                }
                if let failure {
                    Text(failure).foregroundStyle(.red)
                    Button("重新扫码") { code = nil; verification = nil; self.failure = nil; confirmed = false; Task { await enableCamera() } }
                }
            }.padding(24)
                .navigationTitle("扫码登录").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
                .task { await enableCamera() }
                .task(id: confirmed) {
                    guard confirmed, let code else { return }
                    do { try await model.loginWithQRCode(code) { verification = $0 }; dismiss() }
                    catch is CancellationError { }
                    catch { if !Task.isCancelled { failure = error.localizedDescription } }
                }
        }
    }
    private func enableCamera() async {
        guard DataScannerViewController.isSupported else { failure = "此设备不支持扫码，请使用账号密码登录。"; return }
        let allowed = await AVCaptureDevice.requestAccess(for: .video)
        guard !Task.isCancelled else { return }
        guard allowed else { failure = "相机未获授权，请在系统设置中允许 CarryOn 使用相机，或使用账号密码登录。"; return }
        guard DataScannerViewController.isAvailable else { failure = "相机暂不可用，请稍后重试。"; return }
        camera = true
    }
}

private struct QRScanner: UIViewControllerRepresentable {
    let onScan: (String) -> Void
    let onFailure: () -> Void
    func makeCoordinator() -> Coordinator { Coordinator(onScan, onFailure) }
    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], qualityLevel: .balanced, recognizesMultipleItems: false, isGuidanceEnabled: true, isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        do { try scanner.startScanning() } catch { Task { @MainActor in onFailure() } }
        return scanner
    }
    func updateUIViewController(_ uiViewController: DataScannerViewController, context: Context) { }
    static func dismantleUIViewController(_ uiViewController: DataScannerViewController, coordinator: Coordinator) { uiViewController.stopScanning() }
    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let onScan: (String) -> Void
        let onFailure: () -> Void
        var delivered = false
        init(_ onScan: @escaping (String) -> Void, _ onFailure: @escaping () -> Void) { self.onScan = onScan; self.onFailure = onFailure }
        func dataScanner(_ dataScanner: DataScannerViewController, becameUnavailableWithError error: DataScannerViewController.ScanningUnavailable) { onFailure() }
        func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem], allItems: [RecognizedItem]) {
            guard !delivered else { return }
            for item in addedItems {
                if case .barcode(let barcode) = item, let value = barcode.payloadStringValue {
                    delivered = true; dataScanner.stopScanning(); onScan(value); return
                }
            }
        }
    }
}
