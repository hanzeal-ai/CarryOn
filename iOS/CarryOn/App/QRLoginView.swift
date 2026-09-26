import SwiftUI
import AVFoundation
import CarryOnCore

struct QRLoginView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var camera = false
    @State private var preparingCamera = true
    @State private var code: LoginCode?
    @State private var verification: String?
    @State private var failure: String?
    @State private var confirmed = false
    var body: some View {
        NavigationStack {
            VStack(spacing: 22) {
                if preparingCamera { ProgressView("正在准备相机…").frame(maxWidth: .infinity, minHeight: 320) }
                if let code {
                    Image(systemName: "laptopcomputer").font(.system(size: 44))
                    Text(code.address.base.absoluteString).font(.headline).textSelection(.enabled)
                    if let verification {
                        Text(verification).font(.system(size: 36, weight: .semibold, design: .monospaced))
                        Text("在电脑上核对确认码，并允许本次登录。").foregroundStyle(Design.secondary)
                        if failure == nil { ProgressView() }
                    } else {
                        Text("确认登录此云端地址").foregroundStyle(Design.secondary)
                        Button("继续登录") { confirmed = true }.buttonStyle(.borderedProminent).foregroundStyle(Design.onAccent).disabled(confirmed)
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
            }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Design.background)
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
        preparingCamera = true; camera = false; failure = nil
        defer { preparingCamera = false }
        let allowed = await AVCaptureDevice.requestAccess(for: .video)
        guard !Task.isCancelled else { return }
        guard allowed else { failure = "相机未获授权，请在系统设置中允许 CarryOn 使用相机，或使用账号密码登录。"; return }
        camera = true
    }
}

struct QRScanner: UIViewControllerRepresentable {
    let onScan: (String) -> Void
    let onFailure: () -> Void
    func makeUIViewController(context: Context) -> QRScannerController {
        QRScannerController(onScan: onScan, onFailure: onFailure)
    }
    func updateUIViewController(_ controller: QRScannerController, context: Context) {}
    static func dismantleUIViewController(_ controller: QRScannerController, coordinator: ()) { controller.stop() }
}

/// Capture setup/start/stop are serialized off the main thread; UIKit only owns the preview.
final class QRScannerController: UIViewController {
    private let onScan: (String) -> Void
    private let onFailure: () -> Void
    private var active = false
    private var delivered = false
    private var preview: AVCaptureVideoPreviewLayer?
    private lazy var capture: QRCapture = QRCapture { [weak self] value in
        guard let self, self.active, !self.delivered else { return }
        self.delivered = true
        self.capture.stop()
        if let value { self.onScan(value) } else { self.onFailure() }
    }
    init(onScan: @escaping (String) -> Void, onFailure: @escaping () -> Void) {
        self.onScan = onScan; self.onFailure = onFailure
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        let layer = AVCaptureVideoPreviewLayer(session: capture.session)
        layer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(layer); preview = layer
    }
    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
        if let connection = preview?.connection, connection.isVideoRotationAngleSupported(90) { connection.videoRotationAngle = 90 }
    }
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        active = true; delivered = false; capture.start()
    }
    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        stop()
    }
    func stop() { active = false; capture.stop() }
}

private final class QRCapture: NSObject, AVCaptureMetadataOutputObjectsDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "com.hanzeal.carryon.qr-capture", qos: .userInitiated)
    private let completion: @MainActor @Sendable (String?) -> Void
    // Mutated only on queue.
    private var configured = false
    private var delivered = false
    init(completion: @escaping @MainActor @Sendable (String?) -> Void) { self.completion = completion }
    func start() {
        queue.async { [self] in
            delivered = false
            if !configured {
                session.beginConfiguration()
                session.sessionPreset = .high
                guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
                      let input = try? AVCaptureDeviceInput(device: camera), session.canAddInput(input) else {
                    session.commitConfiguration(); finish(nil); return
                }
                session.addInput(input)
                let output = AVCaptureMetadataOutput()
                guard session.canAddOutput(output) else {
                    session.removeInput(input); session.commitConfiguration(); finish(nil); return
                }
                session.addOutput(output)
                guard output.availableMetadataObjectTypes.contains(.qr) else {
                    session.removeOutput(output); session.removeInput(input); session.commitConfiguration(); finish(nil); return
                }
                output.setMetadataObjectsDelegate(self, queue: queue)
                output.metadataObjectTypes = [.qr]
                session.commitConfiguration(); configured = true
            }
            session.startRunning()
            if !session.isRunning { finish(nil) }
        }
    }
    func stop() { queue.async { [self] in delivered = true; session.stopRunning() } }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !delivered, let value = metadataObjects.compactMap({ ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }).first else { return }
        finish(value)
    }
    private func finish(_ value: String?) {
        guard !delivered else { return }
        delivered = true
        Task { @MainActor [completion] in completion(value) }
    }
}
