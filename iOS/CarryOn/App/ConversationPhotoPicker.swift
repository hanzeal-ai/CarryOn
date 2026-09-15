import SwiftUI
import PhotosUI
import CarryOnCore

@MainActor func conversationPhotos(_ selection: [PhotosPickerItem]) async throws -> [String] {
    var result: [String] = []
    for photo in selection {
        guard let data = try await photo.loadTransferable(type: Data.self) else { throw APIError("图片无法读取") }
        try Task.checkCancellation()
        let encoded = try await Task.detached(priority: .userInitiated) {
            try autoreleasepool {
                guard let image = UIImage(data: data) else { throw APIError("图片无法读取") }
                let scale = min(1, 1280 / max(image.size.width, image.size.height))
                let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
                let format = UIGraphicsImageRendererFormat(); format.scale = 1
                let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
                for quality in [0.75, 0.5, 0.3, 0.15] {
                    if let bytes = resized.jpegData(compressionQuality: quality), bytes.count <= 200 * 1024 {
                        return "data:image/jpeg;base64," + bytes.base64EncodedString()
                    }
                }
                throw APIError("图片压缩后仍超过 200 KB，请选择更小的图片")
            }
        }.value
        try Task.checkCancellation()
        result.append(encoded)
    }
    return result
}

struct ConversationPhotoPicker: View {
    @Environment(AppModel.self) private var model
    @Binding var images: [String]
    let disabled: Bool
    @State private var selected: [PhotosPickerItem] = []
    @State private var loading = false
    @State private var generation = UUID()
    var body: some View {
        PhotosPicker(selection: $selected, maxSelectionCount: max(1, 3 - images.count), matching: .images) {
            if loading { ProgressView().frame(width: 44, height: 44) }
            else { Image(systemName: "plus").frame(width: 44, height: 44) }
        }.accessibilityLabel("添加图片").disabled(disabled || loading || images.count >= 3)
            .onChange(of: selected) { _, selection in
                guard !selection.isEmpty else { return }
                let current = UUID(); generation = current; loading = true
                Task {
                    do {
                        let values = try await conversationPhotos(selection)
                        guard generation == current else { return }
                        images = Array((images + values).prefix(3)); selected = []
                    } catch { if generation == current { model.report(error) } }
                    if generation == current { loading = false }
                }
            }
            .onDisappear { generation = UUID(); loading = false }
    }
}
