import SwiftUI
import CarryOnCore

@MainActor @Observable final class TimelineRowPresentation {
    var item: JSONValue
    var markdown: ParsedMessageMarkdown?
    init(item: JSONValue, markdown: ParsedMessageMarkdown?) {
        self.item = item; self.markdown = markdown
    }
}

