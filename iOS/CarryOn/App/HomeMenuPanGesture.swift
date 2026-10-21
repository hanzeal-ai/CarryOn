import SwiftUI
import UIKit

/// Claims horizontal drags before a row can treat their release as a tap.
struct HomeMenuPanGesture: UIViewRepresentable {
    var enabled: Bool
    var menuOpen: Bool
    var changed: (CGFloat) -> Void
    var ended: (CGFloat, CGFloat, Bool) -> Void

    func makeUIView(context: Context) -> PanMarker { PanMarker() }
    func updateUIView(_ view: PanMarker, context: Context) { view.configuration = self }
    static func dismantleUIView(_ view: PanMarker, coordinator: ()) { view.detach() }

    final class PanMarker: UIView, UIGestureRecognizerDelegate {
        var configuration: HomeMenuPanGesture?
        private weak var host: UIView?
        private lazy var pan: UIPanGestureRecognizer = {
            let gesture = UIPanGestureRecognizer(target: self, action: #selector(dragged(_:)))
            gesture.delegate = self
            gesture.maximumNumberOfTouches = 1
            gesture.cancelsTouchesInView = true
            return gesture
        }()

        override func didMoveToWindow() {
            super.didMoveToWindow()
            detach()
            guard window != nil else { return }
            var responder: UIResponder? = self
            while let current = responder {
                if let controller = current as? UIViewController {
                    host = controller.view
                    controller.view.addGestureRecognizer(pan)
                    break
                }
                responder = current.next
            }
        }

        func detach() {
            host?.removeGestureRecognizer(pan)
            host = nil
        }

        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
            guard configuration?.enabled == true, let host, let touched = touch.view else { return false }
            return touched.isDescendant(of: host) && bounds.contains(touch.location(in: self))
        }

        override func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
            guard let configuration, configuration.enabled else { return false }
            let velocity = pan.velocity(in: host)
            return abs(velocity.x) > abs(velocity.y) * 1.3
                && (configuration.menuOpen || velocity.x > 0)
        }

        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            // Keep native scrolling available; taps remain exclusive to the pan.
            other is UIPanGestureRecognizer
        }

        @objc private func dragged(_ gesture: UIPanGestureRecognizer) {
            guard let configuration else { return }
            let translation = gesture.translation(in: host).x
            switch gesture.state {
            case .began, .changed:
                configuration.changed(translation)
            case .ended:
                configuration.ended(translation, gesture.velocity(in: host).x, false)
            case .cancelled, .failed:
                configuration.ended(translation, 0, true)
            default: break
            }
        }
    }
}
