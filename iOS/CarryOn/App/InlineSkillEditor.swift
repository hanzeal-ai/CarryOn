import SwiftUI
import UIKit
import ImageIO
import CarryOnCore

@MainActor enum ComposerTypography {
    static var font: UIFont { UIFontMetrics(forTextStyle: .body).scaledFont(for: .systemFont(ofSize: 15)) }
    static var lineSpacing: CGFloat { UIFontMetrics(forTextStyle: .body).scaledValue(for: 2) }
    static var lineHeight: CGFloat { font.lineHeight + lineSpacing }
    static var paragraphStyle: NSParagraphStyle {
        let style = NSMutableParagraphStyle(); style.lineSpacing = lineSpacing; return style
    }
}

@MainActor enum ReferenceIcon {
    private static let cache: NSCache<NSString, UIImage> = {
        let value = NSCache<NSString, UIImage>(); value.countLimit = 40; value.totalCostLimit = 1024 * 1024; return value
    }()
    static func image(_ encoded: String?) -> UIImage? {
        guard let encoded, encoded.utf8.count <= 87384 else { return nil }
        let key = encoded as NSString
        if let cached = cache.object(forKey: key) { return cached }
        guard let bytes = Data(base64Encoded: encoded), bytes.count >= 33,
              bytes.prefix(8) == Data([137, 80, 78, 71, 13, 10, 26, 10]),
              bytes[12..<16] == Data("IHDR".utf8),
              [16, 20].allSatisfy({ start in let size = bytes[start..<(start + 4)].reduce(0) { $0 * 256 + Int($1) }; return size > 0 && size <= 512 }),
              let source = CGImageSourceCreateWithData(bytes as CFData, nil),
              let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 48, kCGImageSourceShouldCacheImmediately: true] as CFDictionary) else { return nil }
        let image = UIImage(cgImage: thumbnail)
        cache.setObject(image, forKey: key, cost: thumbnail.bytesPerRow * thumbnail.height)
        return image
    }
}

private final class SkillAttachment: NSTextAttachment {
    let reference: ComposerReference
    @MainActor init(_ reference: ComposerReference, font: UIFont) {
        self.reference = reference
        super.init(data: nil, ofType: nil)
        let attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: UIColor.systemBlue]
        let label = reference.label as NSString
        let labelSize = label.size(withAttributes: attributes)
        let scale = font.pointSize / 15
        let iconSize = 16 * scale, labelStart = 22 * scale
        let size = CGSize(width: labelSize.width + labelStart + scale, height: font.lineHeight)
        image = UIGraphicsImageRenderer(size: size).image { _ in
            (ReferenceIcon.image(reference.iconData) ?? UIImage(systemName: reference.isMention ? "square.grid.2x2" : "cube", withConfiguration: UIImage.SymbolConfiguration(pointSize: font.pointSize - 3))?
                .withTintColor(.systemBlue, renderingMode: .alwaysOriginal))?.draw(in: CGRect(x: 2 * scale, y: (font.lineHeight - iconSize) / 2, width: iconSize, height: iconSize))
            label.draw(at: CGPoint(x: labelStart, y: 0), withAttributes: attributes)
        }
        bounds = CGRect(x: 0, y: font.descender, width: size.width, height: size.height)
    }
    required init?(coder: NSCoder) { return nil }
}

private final class SkillTextView: UITextView {
    var focusOnAttach = false
    override func didMoveToWindow() {
        super.didMoveToWindow()
        if window != nil, focusOnAttach {
            focusOnAttach = false
            DispatchQueue.main.async { [weak self] in
                guard let self, self.window != nil, self.isEditable else { return }
                self.becomeFirstResponder()
            }
        }
    }
    override func copy(_ sender: Any?) {
        let value = NSMutableAttributedString(attributedString: attributedText.attributedSubstring(from: selectedRange))
        var tokens: [(NSRange, String)] = []
        value.enumerateAttribute(.attachment, in: NSRange(location: 0, length: value.length)) { attachment, range, _ in
            if let attachment = attachment as? SkillAttachment { tokens.append((range, attachment.reference.label)) }
        }
        for (range, name) in tokens.reversed() { value.replaceCharacters(in: range, with: name) }
        UIPasteboard.general.string = value.string
    }
    override func cut(_ sender: Any?) {
        guard isEditable, let range = selectedTextRange else { return }
        copy(sender); replace(range, withText: ""); delegate?.textViewDidChange?(self)
    }
    override func paste(_ sender: Any?) {
        guard isEditable, let value = UIPasteboard.general.string, let range = selectedTextRange else { return }
        replace(range, withText: value.replacingOccurrences(of: ComposerDocument.marker, with: ""))
        delegate?.textViewDidChange?(self)
    }
}

struct InlineSkillEditor: UIViewRepresentable {
    @Binding var text: String
    @Binding var skills: [ComposerReference]
    @Binding var selection: Int
    var editable: Bool
    var placeholder: String
    var autofocus = false
    var onEditingChanged: ((Bool) -> Void)? = nil

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIView(context: Context) -> UITextView {
        let view = SkillTextView()
        view.focusOnAttach = autofocus
        view.accessibilityIdentifier = "carryon-composer-editor"
        view.delegate = context.coordinator
        view.backgroundColor = .clear
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.adjustsFontForContentSizeCategory = true
        view.keyboardDismissMode = .interactive
        view.isScrollEnabled = false
        view.accessibilityLabel = placeholder
        return view
    }
    func updateUIView(_ view: UITextView, context: Context) {
        context.coordinator.parent = self
        view.isEditable = editable
        view.accessibilityLabel = placeholder
        guard view.markedTextRange == nil else { return }
        let document = ComposerDocument(text: text, skills: skills)
        let font = ComposerTypography.font
        if context.coordinator.rendered != document || context.coordinator.renderedFont != font || view.font != font {
            let previousSelection = context.coordinator.rendered == document ? view.selectedRange : NSRange(location: selection, length: 0)
            context.coordinator.updating = true
            defer { context.coordinator.updating = false }
            let attributed = NSMutableAttributedString(string: document.text, attributes: [.font: font, .foregroundColor: UIColor.label, .paragraphStyle: ComposerTypography.paragraphStyle])
            for skill in document.skills {
                if let offset = skill.offset {
                    attributed.replaceCharacters(in: NSRange(location: offset, length: 1), with: NSAttributedString(attachment: SkillAttachment(skill, font: font)))
                }
            }
            attributed.addAttributes([.font: font, .paragraphStyle: ComposerTypography.paragraphStyle], range: NSRange(location: 0, length: attributed.length))
            view.attributedText = attributed
            view.font = font
            view.typingAttributes = [.font: font, .foregroundColor: UIColor.label, .paragraphStyle: ComposerTypography.paragraphStyle]
            let start = min(max(0, previousSelection.location), attributed.length)
            view.selectedRange = NSRange(location: start, length: min(max(0, previousSelection.length), attributed.length - start))
            view.accessibilityValue = document.displayText
            context.coordinator.rendered = document
            context.coordinator.renderedFont = font
        }
    }
    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        guard let width = proposal.width else { return nil }
        let line = ComposerTypography.lineHeight
        let size = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        uiView.textContainer.size = CGSize(width: width, height: .greatestFiniteMagnitude)
        let layout = uiView.layoutManager
        layout.ensureLayout(for: uiView.textContainer)
        var count = 0, sixthLineBottom: CGFloat = 0
        layout.enumerateLineFragments(forGlyphRange: layout.glyphRange(for: uiView.textContainer)) { rect, _, _, _, stop in
            count += 1
            if count == 6 { sixthLineBottom = rect.maxY; stop.pointee = true }
        }
        let limit = count < 6 ? size.height : sixthLineBottom
        let height = max(line, min(limit, size.height))
        uiView.isScrollEnabled = size.height > height + 0.5
        return CGSize(width: width, height: height)
    }
    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: InlineSkillEditor
        var rendered: ComposerDocument?
        var renderedFont: UIFont?
        var updating = false
        func textViewDidBeginEditing(_ textView: UITextView) { parent.onEditingChanged?(true) }
        func textViewDidEndEditing(_ textView: UITextView) { parent.onEditingChanged?(false) }
        func textViewDidChangeSelection(_ textView: UITextView) {
            if !updating { parent.selection = textView.selectedRange.location }
        }
        init(_ parent: InlineSkillEditor) { self.parent = parent }
        func textViewDidChange(_ textView: UITextView) {
            var references: [ComposerReference] = []
            let value = textView.attributedText ?? NSAttributedString()
            value.enumerateAttribute(.attachment, in: NSRange(location: 0, length: value.length)) { attachment, range, _ in
                guard let attachment = attachment as? SkillAttachment else { return }
                references.append(.init(name: attachment.reference.name, path: attachment.reference.path, offset: range.location, displayName: attachment.reference.displayName, iconData: attachment.reference.iconData))
            }
            parent.text = value.string; parent.skills = references
            parent.selection = textView.selectedRange.location
            rendered = ComposerDocument(text: value.string, skills: references)
            textView.accessibilityValue = rendered?.displayText
            textView.invalidateIntrinsicContentSize()
        }
    }
}
