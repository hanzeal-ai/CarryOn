import SwiftUI
import UIKit

private struct ConversationSelectionChangedKey: EnvironmentKey {
    static let defaultValue: (@MainActor @Sendable (UITextView) -> Void)? = nil
}
extension EnvironmentValues {
    var conversationSelectionChanged: (@MainActor @Sendable (UITextView) -> Void)? {
        get { self[ConversationSelectionChangedKey.self] }
        set { self[ConversationSelectionChangedKey.self] = newValue }
    }
}

@MainActor final class ConversationNavigationTracker: NSObject {
    final class Entry { weak var view: UIView?; init(_ view: UIView) { self.view = view } }
    var entries: [String: Entry] = [:]
    @MainActor final class Selection {
        weak var source: UITextView?
        let range: NSRange
        var restored = false
        init(_ view: UITextView) { source = view; range = view.selectedRange }
    }
    struct ReadingAnchor {
        let id: String
        let text: String?
        let paragraph: Int
        let preceding: [String]
        let offset: Int
        let screenY: CGFloat
        let intent: UInt64
        let viewport: CGRect
        let contentOffset: CGFloat
        let selection: Selection?
    }
    private weak var observedTable: UITableView?
    private var restoringSelection = false
    func selectionChanged(_ view: UITextView) {
        guard !restoringSelection else { return }
        if !view.isFirstResponder, view.window != nil { cancelReadingRestoration(); return }
        if let selection = pendingReadingAnchor?.selection, selection.source === view, view.selectedRange == selection.range { return }
        if view.isFirstResponder || pendingReadingAnchor?.selection?.source === view { cancelReadingRestoration() }
    }
    private var readingIntent: UInt64 = 0
    private var readingValidity: (() -> Bool)?
    private var pendingReadingAnchor: ReadingAnchor?
    private var readingRepairID = UUID()
    private var readingRepairs = 0
    private var readingRecoveryAttempted = false
    private func sameViewport(_ first: CGRect, _ second: CGRect) -> Bool {
        abs(first.minX - second.minX) < 0.5 && abs(first.minY - second.minY) < 0.5 &&
        abs(first.width - second.width) < 0.5 && abs(first.height - second.height) < 0.5
    }
    func cancelReadingRestoration() { readingIntent &+= 1; pendingReadingAnchor = nil; readingValidity = nil; readingRepairID = UUID() }
    @objc private func readingPanChanged(_ recognizer: UIPanGestureRecognizer) {
        if recognizer.state != .possible { cancelReadingRestoration() }
    }
    private func cell(for id: String) -> UITableViewCell? {
        guard let marker = entries[id]?.view, marker.accessibilityIdentifier == "conversation-message-" + id else { return nil }
        var parent = marker.superview
        while let view = parent {
            if let cell = view as? UITableViewCell {
                guard let table, !cell.isHidden, table.visibleCells.contains(where: { $0 === cell }), let index = table.indexPath(for: cell), table.indexPathsForVisibleRows?.contains(index) == true else { return nil }
                return cell
            }
            parent = view.superview
        }
        return nil
    }
    func captureVisiblePosition() -> (id: String, offset: CGFloat)? {
        guard let table else { return nil }
        let viewport = table.convert(table.bounds, to: nil)
        for (id, frame) in frames.sorted(by: { $0.value.minY < $1.value.minY }) where frame.intersects(viewport) {
            guard let cell = cell(for: id), let index = table.indexPath(for: cell) else { continue }
            return (id, table.contentOffset.y - (table.rectForRow(at: index).maxY - table.bounds.height))
        }
        return nil
    }
    private func textViews(in view: UIView) -> [UITextView] {
        if let text = view as? UITextView { return text.isEditable ? [] : [text] }
        return view.subviews.flatMap { textViews(in: $0) }
    }
    private func firstResponder(in view: UIView) -> UIView? {
        if view.isFirstResponder { return view }
        return view.subviews.lazy.compactMap { self.firstResponder(in: $0) }.first
    }
    func captureReadingAnchor(in ids: Set<String>) -> ReadingAnchor? {
        guard !ids.isEmpty, let table, table.contentOffset.y > 0.5, !table.isDragging, !table.isDecelerating else { return nil }
        if observedTable !== table {
            observedTable?.panGestureRecognizer.removeTarget(self, action: #selector(readingPanChanged))
            observedTable = table
            table.panGestureRecognizer.addTarget(self, action: #selector(readingPanChanged))
        }
        let viewport = table.convert(table.bounds, to: nil)
        let frameSnapshot = frames
        let continuingID = pendingReadingAnchor.flatMap { anchor in
            anchor.intent == readingIntent && sameViewport(anchor.viewport, viewport) && readingValidity?() == true ? anchor.id : nil
        }
        let candidates = ids.compactMap { id -> (String, CGRect, [UITextView])? in
            guard let frame = frameSnapshot[id], frame.intersects(viewport), let cell = cell(for: id) else { return nil }
            return (id, frame, textViews(in: cell))
        }.sorted {
            let firstSelected = $0.2.contains { $0.isFirstResponder && $0.selectedRange.length > 0 }
            let secondSelected = $1.2.contains { $0.isFirstResponder && $0.selectedRange.length > 0 }
            if firstSelected != secondSelected { return firstSelected }
            if ($0.0 == continuingID) != ($1.0 == continuingID) { return $0.0 == continuingID }
            return $0.1.minY < $1.1.minY
        }
        for (id, frame, paragraphs) in candidates {
            for (index, view) in paragraphs.enumerated().sorted(by: { ($0.element.isFirstResponder && $0.element.selectedRange.length > 0 ? 0 : 1, $0.offset) < ($1.element.isFirstResponder && $1.element.selectedRange.length > 0 ? 0 : 1, $1.offset) }) {
                let text = view.text ?? ""
                let visible = view.convert(view.bounds, to: nil).intersection(viewport)
                guard !text.isEmpty, !visible.isNull, visible.height > 1,
                      let position = view.closestPosition(to: view.convert(CGPoint(x: visible.minX + 1, y: visible.minY + 1), from: nil)),
                      let end = view.position(from: position, offset: 1), let range = view.textRange(from: position, to: end) else { continue }
                let rect = view.convert(view.firstRect(for: range), to: nil)
                guard rect.height > 0, rect.intersects(viewport) else { continue }
                return .init(id: id, text: text, paragraph: index, preceding: paragraphs.prefix(index).map { $0.text ?? "" },
                             offset: view.offset(from: view.beginningOfDocument, to: position), screenY: rect.minY, intent: readingIntent, viewport: viewport, contentOffset: table.contentOffset.y, selection: view.isFirstResponder && view.selectedRange.length > 0 ? Selection(view) : nil)
            }
            return .init(id: id, text: nil, paragraph: 0, preceding: [], offset: 0, screenY: frame.minY, intent: readingIntent, viewport: viewport, contentOffset: table.contentOffset.y, selection: nil)
        }
        return nil
    }
    func restoreReadingAnchor(_ anchor: ReadingAnchor, valid: @escaping () -> Bool) {
        readingValidity = valid; pendingReadingAnchor = anchor; readingRepairs = 0; readingRecoveryAttempted = false; readingRepairID = UUID()
        let repairID = readingRepairID
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.75) { [weak self] in
            guard let self, readingRepairID == repairID else { return }; pendingReadingAnchor = nil; readingValidity = nil
        }
        repairReadingAnchor()
    }
    private func repairReadingAnchor() {
        guard let anchor = pendingReadingAnchor, readingRepairs < 3 else { return }
        guard readingValidity?() == true else { cancelReadingRestoration(); return }
        guard anchor.intent == readingIntent, let table, observedTable === table,
              !table.isDragging, !table.isDecelerating, sameViewport(table.convert(table.bounds, to: nil), anchor.viewport) else { cancelReadingRestoration(); return }
        table.layoutIfNeeded()
        guard anchor.intent == readingIntent, readingValidity?() == true else { return }
        let screenY: CGFloat
        if let text = anchor.text {
            guard let cell = cell(for: anchor.id) else {
                guard !readingRecoveryAttempted, abs(table.contentOffset.y - anchor.contentOffset) > 0.5 else { return }
                readingRecoveryAttempted = true; readingRepairs += 1
                let maximum = max(0, table.contentSize.height - table.bounds.height + table.adjustedContentInset.bottom)
                table.setContentOffset(CGPoint(x: 0, y: min(maximum, max(0, anchor.contentOffset))), animated: false)
                didLayout()
                return
            }
            let paragraphs = textViews(in: cell)
            guard paragraphs.indices.contains(anchor.paragraph),
                  paragraphs.prefix(anchor.paragraph).map({ $0.text ?? "" }) == anchor.preceding else { return }
            let view = paragraphs[anchor.paragraph]
            guard (view.text ?? "").hasPrefix(text) else { return }
            guard let position = view.position(from: view.beginningOfDocument, offset: anchor.offset),
                  let end = view.position(from: position, offset: 1), let range = view.textRange(from: position, to: end) else { return }
            screenY = view.convert(view.firstRect(for: range), to: nil).minY
            if let selection = anchor.selection, NSMaxRange(selection.range) <= (view.text as NSString).length {
                if selection.source === view {
                    guard view.isFirstResponder, view.selectedRange == selection.range else { cancelReadingRestoration(); return }
                } else if !selection.restored {
                    let focused = firstResponder(in: table.window ?? table)
                    guard focused == nil || focused === selection.source || focused === view else { cancelReadingRestoration(); return }
                    restoringSelection = true
                    if !view.isFirstResponder { view.becomeFirstResponder() }
                    view.selectedRange = selection.range
                    selection.source = view; selection.restored = true
                    restoringSelection = false
                }
            }
        } else {
            guard let frame = frames[anchor.id] else { return }; screenY = frame.minY
        }
        let delta = anchor.screenY - screenY
        guard anchor.intent == readingIntent, abs(delta) > 0.5 else { return }
        let maximum = max(0, table.contentSize.height - table.bounds.height + table.adjustedContentInset.bottom)
        readingRepairs += 1
        table.setContentOffset(CGPoint(x: 0, y: min(maximum, max(0, table.contentOffset.y + delta))), animated: false)
    }
    var onLayout: (() -> Void)?
    private var layoutPending = false
    func didLayout() {
        guard !layoutPending else { return }
        layoutPending = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            layoutPending = false; repairReadingAnchor(); onLayout?()
        }
    }
    private var table: UITableView? {
        for entry in entries.values {
            var parent = entry.view?.superview
            while let view = parent {
                if let table = view as? UITableView, table.window != nil, table.bounds.height > 0 {
                    return table
                }
                parent = view.superview
            }
        }
        return nil
    }
    var contentOffset: CGFloat? { table?.contentOffset.y }
    var viewportBounds: CGRect? { table.map { $0.convert($0.bounds, to: nil) } }
    var measuredLayout: CGRect? {
        guard let table else { return nil }
        table.layoutIfNeeded()
        return CGRect(x: table.contentOffset.y, y: table.contentSize.height, width: table.bounds.width, height: table.bounds.height)
    }
    var isDragging: Bool {
        for entry in entries.values {
            var parent = entry.view?.superview
            while let view = parent {
                if let scroll = view as? UIScrollView, scroll.isDragging { return true }
                parent = view.superview
            }
        }
        return false
    }
    var frames: [String: CGRect] {
        entries = entries.filter { $0.value.view != nil }
        return entries.reduce(into: [:]) { result, pair in
            if pair.key != "carryon:status", let view = pair.value.view, view.window != nil, view.accessibilityIdentifier == "conversation-message-" + pair.key {
                result[pair.key] = view.convert(view.bounds, to: nil)
            }
        }
    }
}
struct ConversationNavigationMarker: UIViewRepresentable {
    let id: String
    let tracker: ConversationNavigationTracker
    final class MarkerView: UIView {
        weak var tracker: ConversationNavigationTracker?
        override func layoutSubviews() { super.layoutSubviews(); tracker?.didLayout() }
    }
    func makeUIView(context: Context) -> MarkerView { let view = MarkerView(); view.tracker = tracker; view.isUserInteractionEnabled = false; tracker.entries[id] = .init(view); return view }
    func updateUIView(_ view: MarkerView, context: Context) {
        view.tracker = tracker
        if let identifier = view.accessibilityIdentifier {
            let previous = String(identifier.dropFirst("conversation-message-".count))
            if previous != id, tracker.entries[previous]?.view === view { tracker.entries.removeValue(forKey: previous) }
        }
        view.accessibilityIdentifier = "conversation-message-" + id
        tracker.entries[id] = .init(view)
    }
}
