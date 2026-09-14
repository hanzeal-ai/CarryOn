import SwiftUI

struct DraftImageThumbnail: View {
    let dataURL: String
    let remove: () -> Void
    @State private var image: UIImage?
    @State private var preview = false

    var body: some View {
        VStack(spacing: 2) {
            Button { preview = true } label: {
                Group {
                    if let image { Image(uiImage: image).resizable().scaledToFill() }
                    else { Image(systemName: "photo").foregroundStyle(Design.secondary) }
                }.frame(width: 88, height: 88).clipped()
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }.buttonStyle(.plain).disabled(image == nil).accessibilityLabel("预览待发送图片")
                .overlay(alignment: .topTrailing) {
                    Button(action: remove) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 20)).symbolRenderingMode(.palette)
                            .foregroundStyle(.white, .black.opacity(0.65))
                            .frame(width: 32, height: 32)
                    }.buttonStyle(.plain).accessibilityLabel("删除此图片")
                }
            Button("删除", action: remove).font(.caption).foregroundStyle(.red)
                .frame(minHeight: 32).accessibilityLabel("删除此图片")
        }
        .background(ImageLightboxPresenter(image: image, isPresented: $preview, onDelete: remove).frame(width: 0, height: 0))
        .task(id: dataURL) {
            image = nil
            guard let comma = dataURL.firstIndex(of: ","),
                  let data = Data(base64Encoded: String(dataURL[dataURL.index(after: comma)...])) else { return }
            image = UIImage(data: data)
        }
    }
}
