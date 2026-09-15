import SwiftUI
import UIKit

/// Presents above the conversation so its content remains visible beneath the mask.
struct ImageLightboxPresenter: UIViewControllerRepresentable {
    let image: UIImage?
    @Binding var isPresented: Bool
    var onDelete: (() -> Void)? = nil

    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeUIViewController(context: Context) -> ImagePresentationHost {
        let controller = ImagePresentationHost()
        let coordinator = context.coordinator
        controller.ready = { [weak controller, weak coordinator] in
            if let controller { coordinator?.presentIfReady(from: controller) }
        }
        return controller
    }
    func updateUIViewController(_ controller: ImagePresentationHost, context: Context) {
        let coordinator = context.coordinator
        coordinator.binding = $isPresented
        coordinator.image = image
        coordinator.onDelete = onDelete
        coordinator.presentIfReady(from: controller)
        if !isPresented { coordinator.preview?.close() }
    }
    static func dismantleUIViewController(_ controller: ImagePresentationHost, coordinator: Coordinator) {
        controller.ready = nil
        coordinator.preview?.dismiss(animated: false)
        coordinator.preview = nil
        coordinator.binding = nil
    }
    @MainActor final class Coordinator {
        var binding: Binding<Bool>?
        var image: UIImage?
        var onDelete: (() -> Void)?
        var preview: ImageLightboxController?
        var scheduled = false
        func presentIfReady(from controller: UIViewController) {
            guard binding?.wrappedValue == true, image != nil, preview == nil, !scheduled else { return }
            scheduled = true
            DispatchQueue.main.async { [weak self, weak controller] in
                guard let self else { return }
                self.scheduled = false
                guard let controller, self.binding?.wrappedValue == true, let image = self.image,
                      self.preview == nil, var presenter = controller.view.window?.rootViewController else { return }
                while let presented = presenter.presentedViewController, !presented.isBeingDismissed { presenter = presented }
                let preview = ImageLightboxController(image: image)
                preview.onDelete = self.onDelete
                preview.onClose = { [weak self] in self?.preview = nil; self?.binding?.wrappedValue = false }
                self.preview = preview
                presenter.present(preview, animated: !UIAccessibility.isReduceMotionEnabled)
            }
        }
    }
}

// A Markdown link can load its image before its background presenter joins the window.
// Retry on attachment instead of losing that first presentation request.
final class ImagePresentationHost: UIViewController {
    var ready: (() -> Void)?
    override func loadView() {
        let anchor = ImagePresentationAnchor()
        anchor.backgroundColor = .clear
        anchor.isUserInteractionEnabled = false
        anchor.ready = { [weak self] in self?.ready?() }
        view = anchor
    }
    override func viewDidAppear(_ animated: Bool) { super.viewDidAppear(animated); ready?() }
}
private final class ImagePresentationAnchor: UIView {
    var ready: (() -> Void)?
    override func didMoveToWindow() { super.didMoveToWindow(); if window != nil { ready?() } }
}

final class ImageLightboxController: UIViewController, UIScrollViewDelegate, UIGestureRecognizerDelegate {
    var onClose: (() -> Void)?
    var onDelete: (() -> Void)?
    private let image: UIImage
    private let mask = UIView()
    private let scroll = UIScrollView()
    private let picture = UIImageView()
    private let closeButton = UIButton(type: .system)
    private let deleteButton = UIButton(type: .system)
    private var laidOutSize = CGSize.zero
    private var closing = false
    private lazy var drag = UIPanGestureRecognizer(target: self, action: #selector(dragged(_:)))
    private lazy var singleTap = UITapGestureRecognizer(target: self, action: #selector(tappedMask))
    private lazy var doubleTap = UITapGestureRecognizer(target: self, action: #selector(zoomed(_:)))

    init(image: UIImage) {
        self.image = image
        super.init(nibName: nil, bundle: nil)
        modalPresentationStyle = .overFullScreen
        modalTransitionStyle = .crossDissolve
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        view.accessibilityViewIsModal = true
        mask.backgroundColor = .black
        mask.alpha = 0.82
        view.addSubview(mask)
        scroll.delegate = self
        scroll.backgroundColor = .clear
        scroll.contentInsetAdjustmentBehavior = .never
        scroll.showsHorizontalScrollIndicator = false
        scroll.showsVerticalScrollIndicator = false
        scroll.bounces = false
        view.addSubview(scroll)
        picture.image = image
        picture.contentMode = .scaleAspectFit
        picture.isAccessibilityElement = true
        picture.accessibilityLabel = "原图"
        picture.accessibilityCustomActions = [UIAccessibilityCustomAction(name: "放大或还原", target: self, selector: #selector(accessibleZoom))]
        scroll.addSubview(picture)
        closeButton.setImage(UIImage(systemName: "xmark"), for: .normal)
        closeButton.tintColor = .white
        closeButton.accessibilityLabel = "关闭图片预览"
        closeButton.addTarget(self, action: #selector(tappedMask), for: .touchUpInside)
        view.addSubview(closeButton)
        if onDelete != nil {
            deleteButton.setTitle("删除图片", for: .normal)
            deleteButton.setTitleColor(.systemRed, for: .normal)
            deleteButton.tintColor = .systemRed
            deleteButton.backgroundColor = .clear
            deleteButton.layer.borderWidth = 1
            deleteButton.layer.borderColor = UIColor.systemRed.cgColor
            deleteButton.layer.cornerRadius = 12
            deleteButton.addTarget(self, action: #selector(deleteImage), for: .touchUpInside)
            view.addSubview(deleteButton)
        }
        drag.maximumNumberOfTouches = 1
        drag.delegate = self
        view.addGestureRecognizer(drag)
        scroll.panGestureRecognizer.require(toFail: drag)
        doubleTap.numberOfTapsRequired = 2
        doubleTap.delegate = self
        singleTap.delegate = self
        singleTap.require(toFail: doubleTap)
        view.addGestureRecognizer(singleTap)
        view.addGestureRecognizer(doubleTap)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        mask.frame = view.bounds
        closeButton.frame = CGRect(x: view.bounds.width - view.safeAreaInsets.right - 52,
                                   y: view.safeAreaInsets.top + 4, width: 44, height: 44)
        deleteButton.frame = CGRect(x: (view.bounds.width - 140) / 2,
                                    y: view.bounds.height - view.safeAreaInsets.bottom - 60, width: 140, height: 44)
        guard laidOutSize != view.bounds.size, view.bounds.width > 0, image.size.width > 0, image.size.height > 0 else { return }
        laidOutSize = view.bounds.size
        scroll.transform = .identity
        scroll.frame = view.bounds
        scroll.minimumZoomScale = 1
        scroll.maximumZoomScale = 1
        scroll.zoomScale = 1
        picture.frame = CGRect(origin: .zero, size: image.size)
        scroll.contentSize = image.size
        let availableHeight = max(1, view.bounds.height - view.safeAreaInsets.top - view.safeAreaInsets.bottom)
        let fit = min(view.bounds.width / image.size.width, availableHeight / image.size.height, 1)
        scroll.minimumZoomScale = fit
        scroll.maximumZoomScale = max(1, fit * 5)
        scroll.setZoomScale(fit, animated: false)
        centerImage()
    }
    func viewForZooming(in scrollView: UIScrollView) -> UIView? { picture }
    func scrollViewDidZoom(_ scrollView: UIScrollView) { centerImage() }
    private func centerImage() {
        let horizontal = max(0, (scroll.bounds.width - scroll.contentSize.width) / 2)
        let vertical = max(0, (scroll.bounds.height - scroll.contentSize.height) / 2)
        scroll.contentInset = UIEdgeInsets(top: vertical, left: horizontal, bottom: vertical, right: horizontal)
    }
    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        guard !(touch.view is UIControl) else { return false }
        let insideImage = picture.bounds.contains(touch.location(in: picture))
        if gestureRecognizer === singleTap { return !insideImage }
        if gestureRecognizer === doubleTap { return insideImage }
        return true
    }
    func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
        guard gestureRecognizer === drag else { return !closing }
        let velocity = drag.velocity(in: view)
        return !closing && scroll.zoomScale <= scroll.minimumZoomScale + 0.001
            && velocity.y > abs(velocity.x) && drag.numberOfTouches == 1
    }
    @objc private func zoomed(_ recognizer: UITapGestureRecognizer) {
        toggleZoom(at: recognizer.location(in: picture))
    }
    @objc private func accessibleZoom() -> Bool {
        toggleZoom(at: CGPoint(x: picture.bounds.midX, y: picture.bounds.midY))
        return true
    }
    private func toggleZoom(at point: CGPoint) {
        let animated = !UIAccessibility.isReduceMotionEnabled
        if scroll.zoomScale > scroll.minimumZoomScale + 0.001 {
            scroll.setZoomScale(scroll.minimumZoomScale, animated: animated)
        } else {
            let scale = min(scroll.maximumZoomScale, scroll.minimumZoomScale * 2.5)
            let size = CGSize(width: scroll.bounds.width / scale, height: scroll.bounds.height / scale)
            scroll.zoom(to: CGRect(x: point.x - size.width / 2, y: point.y - size.height / 2,
                                   width: size.width, height: size.height), animated: animated)
        }
    }
    @objc private func dragged(_ recognizer: UIPanGestureRecognizer) {
        let translation = recognizer.translation(in: view)
        switch recognizer.state {
        case .changed:
            let distance = max(0, translation.y)
            scroll.transform = CGAffineTransform(translationX: translation.x * 0.15, y: distance)
            mask.alpha = 0.82 * max(0.15, 1 - distance / max(1, view.bounds.height * 0.7))
            closeButton.alpha = mask.alpha / 0.82
        case .ended:
            if translation.y > max(100, view.bounds.height * 0.18) || (translation.y > 25 && recognizer.velocity(in: view).y > 900) {
                close(sliding: true)
            } else { restorePosition() }
        case .cancelled, .failed: restorePosition()
        default: break
        }
    }
    private func restorePosition() {
        UIView.animate(withDuration: UIAccessibility.isReduceMotionEnabled ? 0 : 0.2) {
            self.scroll.transform = .identity
            self.mask.alpha = 0.82
            self.closeButton.alpha = 1
        }
    }
    @objc private func deleteImage() {
        guard !closing else { return }
        let didClose = onClose, remove = onDelete
        onClose = { didClose?(); remove?() }
        close()
    }
    @objc private func tappedMask() { close() }
    override func accessibilityPerformEscape() -> Bool { close(); return true }
    func close(sliding: Bool = false) {
        guard !closing else { return }
        closing = true
        UIView.animate(withDuration: UIAccessibility.isReduceMotionEnabled ? 0 : 0.2, animations: {
            self.mask.alpha = 0
            self.closeButton.alpha = 0
            self.deleteButton.alpha = 0
            self.scroll.alpha = 0
            if sliding && !UIAccessibility.isReduceMotionEnabled {
                self.scroll.transform = CGAffineTransform(translationX: 0, y: self.view.bounds.height)
            }
        }, completion: { _ in self.dismiss(animated: false) { self.onClose?() } })
    }
}
