import SwiftUI

struct ReasoningEffortControl: View {
    let modelName: String
    let effort: String
    let efforts: [String]
    let disabled: Bool
    let advanced: () -> Void
    let choose: (String) -> Void

    var body: some View {
        VStack(spacing: 20) {
            Button(action: advanced) {
                HStack(spacing: 6) {
                    Text(modelName).fontWeight(.medium)
                    Text(ModelPresentation.effort(effort)).foregroundStyle(.secondary)
                    Image(systemName: "chevron.right").font(.subheadline.weight(.semibold))
                }.font(.title3).frame(minHeight: 44)
            }.accessibilityLabel("模型与思考强度")
            if !efforts.isEmpty {
                GeometryReader { geometry in
                    HStack(spacing: 0) {
                        ForEach(efforts, id: \.self) { value in
                            Button { choose(value) } label: {
                                ZStack {
                                    Circle().fill(value == effort ? .clear : Color.secondary.opacity(0.3)).frame(width: 12, height: 12)
                                    if value == effort { Circle().strokeBorder(Design.ink, lineWidth: 3).frame(width: 42, height: 42) }
                                }.frame(maxWidth: .infinity).frame(height: 52).contentShape(Rectangle())
                            }.buttonStyle(.plain).accessibilityLabel(ModelPresentation.effort(value))
                                .accessibilityAddTraits(value == effort ? .isSelected : [])
                        }
                    }
                    .background(Design.surface, in: Capsule())
                    .gesture(DragGesture(minimumDistance: 8).onEnded { event in
                        guard !disabled, geometry.size.width > 0 else { return }
                        let index = min(efforts.count - 1, max(0, Int(event.location.x / geometry.size.width * CGFloat(efforts.count))))
                        choose(efforts[index])
                    })
                }.frame(height: 52).disabled(disabled)
            }
        }.foregroundStyle(Design.ink).padding(.horizontal, 32).padding(.bottom, 12)
    }
}

/// The quick selector stays over the composer; only advanced settings present a sheet.
struct ReasoningEffortOverlay<Content: View>: View {
    let close: () -> Void
    @ViewBuilder var content: Content
    var body: some View {
        ZStack(alignment: .bottom) {
            Color.clear.contentShape(Rectangle()).onTapGesture(perform: close)
                .accessibilityLabel("关闭模型选择").accessibilityAddTraits(.isButton)
            content.padding(.top, 24).padding(.bottom, 8).frame(maxWidth: .infinity)
                .background {
                    Rectangle().fill(.ultraThinMaterial)
                        .mask(LinearGradient(colors: [.clear, .black, .black], startPoint: .top, endPoint: .bottom))
                        .padding(.top, -80).ignoresSafeArea(edges: .bottom)
                }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
